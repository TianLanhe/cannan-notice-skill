import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        script = ROOT / 'scripts' / 'bootstrap.py'
        if not script.exists():
            self.fail('isolated runtime bootstrap is not implemented')
        spec = importlib.util.spec_from_file_location('cannan_bootstrap_test', script)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'skill with spaces'
        self.root.mkdir()
        (self.root / 'requirements.txt').write_text('# controlled test dependencies\n')
        shutil.copytree(ROOT / 'scripts', self.root / 'scripts')
        (self.root / 'cannan.py').write_text('import json,sys; print(json.dumps(sys.argv[1:])); sys.exit(3)\n')
        self.cache = Path(self.temp.name) / 'cache'
        self.installs = []
        self.fail_install = False
        self.original_run = subprocess.run

    def network_double(self, args, **kwargs):
        # Real venv creation and imports; replace only network pip installation.
        if args[1:4] == ['-m', 'pip', 'install']:
            self.installs.append(tuple(args))
            if self.fail_install:
                raise subprocess.CalledProcessError(1, args)
            destination = Path(self.original_run([args[0], '-c', 'import site;print(site.getsitepackages()[0])'], capture_output=True, text=True, check=True).stdout.strip())
            for name in ('pypdf', 'pypdfium2', 'pypdfium2_raw', 'pypdfium2_cfg', 'PIL'):
                source = Path(importlib.util.find_spec(name).origin)
                if source.name == '__init__.py':
                    shutil.copytree(source.parent, destination / name, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, destination / source.name)
            return subprocess.CompletedProcess(args, 0)
        return self.original_run(args, **kwargs)

    def prepare(self):
        return self.module.prepare_environment(self.root, self.cache, sys.executable)

    def test_second_call_reuses_environment_and_changed_requirements_do_not(self):
        with patch.object(self.module.subprocess, 'run', side_effect=self.network_double):
            first = self.prepare()
            second = self.prepare()
            self.assertEqual(first, second)
            self.assertEqual(len(self.installs), 1)
            (self.root / 'requirements.txt').write_text('# changed dependencies\n')
            third = self.prepare()
        self.assertNotEqual(first, third)
        self.assertEqual(len(self.installs), 2)
        result = self.original_run([str(first), '-c', 'import pypdf,pypdfium2,PIL;print("ready")'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'ready')

    def test_failed_install_can_recover_without_reusing_partial_environment(self):
        with patch.object(self.module.subprocess, 'run', side_effect=self.network_double):
            self.fail_install = True
            with self.assertRaises(RuntimeError):
                self.prepare()
            self.fail_install = False
            python = self.prepare()
        self.assertEqual(len(self.installs), 2)
        self.assertTrue(python.exists())
        self.assertEqual(self.original_run([str(python), '-c', 'import pypdf,pypdfium2,PIL']).returncode, 0)

    def test_concurrent_first_calls_install_once(self):
        with patch.object(self.module.subprocess, 'run', side_effect=self.network_double), concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            paths = list(pool.map(lambda _: self.prepare(), range(2)))
        self.assertEqual(paths[0], paths[1])
        self.assertEqual(len(self.installs), 1)

    def test_launcher_is_cwd_independent_preserves_arguments_and_exit_code(self):
        with patch.object(self.module.subprocess, 'run', side_effect=self.network_double):
            self.prepare()
        environment = dict(os.environ, CANNAN_PYTHON=sys.executable, CANNAN_CACHE_DIR=str(self.cache), HOME=str(Path(self.temp.name) / 'empty-home'))
        result = self.original_run([str(self.root / 'scripts' / 'cannan'), '--example', 'argument with spaces'], cwd=self.temp.name, env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout), ['--example', 'argument with spaces'])
        self.assertFalse((Path(environment['HOME']) / '.local').exists())

    def test_launcher_missing_curl_or_explicit_python_reports_error(self):
        launcher = str(self.root / 'scripts' / 'cannan')
        result = self.original_run([launcher], env=dict(os.environ, PATH=self.temp.name, CANNAN_PYTHON=sys.executable), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('curl', result.stderr)
        result = self.original_run([launcher], env=dict(os.environ, CANNAN_PYTHON='/missing/python'), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('CANNAN_PYTHON', result.stderr)
        old = Path(self.temp.name) / 'old-python'
        old.write_text('#!/bin/sh\nexit 1\n')
        old.chmod(0o755)
        result = self.original_run([launcher], env=dict(os.environ, CANNAN_PYTHON=str(old)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('3.10', result.stderr)
