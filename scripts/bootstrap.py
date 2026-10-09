"""Prepare a private cached venv and execute this installation's CLI."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

DEPENDENCY_CHECK = 'import pypdf,pypdfium2,PIL'


def cache_directory() -> Path:
    if os.environ.get('CANNAN_CACHE_DIR'):
        return Path(os.environ['CANNAN_CACHE_DIR']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Caches' / 'cannan-notice'
    return Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))).expanduser() / 'cannan-notice'


def prepare_environment(root: Path, cache_root: Path, python_executable: str) -> Path:
    root, cache_root = Path(root).resolve(), Path(cache_root).expanduser().resolve()
    interpreter = str(Path(python_executable).resolve())
    try:
        info = subprocess.run([interpreter, '-c', 'import sys,platform,json;print(json.dumps([sys.version,platform.machine()]))'], capture_output=True, text=True, check=True).stdout
        requirements = root / 'requirements.txt'
        fingerprint = hashlib.sha256(b'cannan-runtime-v1\0' + interpreter.encode() + info.encode() + requirements.read_bytes()).hexdigest()[:24]
        cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        environment = cache_root / fingerprint
        python = environment / 'bin' / 'python'
        marker = environment / '.complete'
        lock_path = cache_root / (fingerprint + '.lock')
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(lock_fd, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if marker.is_file() and python.is_file():
                ready = subprocess.run([str(python), '-c', DEPENDENCY_CHECK], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if ready.returncode == 0:
                    return python
            # Only this keyed application environment is replaced on failure.
            if environment.exists():
                shutil.rmtree(environment)
            environment.mkdir(mode=0o700)
            try:
                print('正在准备迦南通知的独立 Python 环境…', file=sys.stderr)
                subprocess.run([interpreter, '-m', 'venv', str(environment)], check=True, stdout=sys.stderr, stderr=sys.stderr)
                subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(requirements)], check=True, stdout=sys.stderr, stderr=sys.stderr)
                subprocess.run([str(python), '-c', DEPENDENCY_CHECK], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                marker.write_text(fingerprint + '\n')
                marker.chmod(0o600)
            except (OSError, subprocess.SubprocessError):
                shutil.rmtree(environment, ignore_errors=True)
                raise RuntimeError('独立运行环境准备失败，请检查 Python、网络及依赖安装结果。') from None
            return python
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('无法检查解释器、读取依赖清单或创建用户缓存目录。') from None


def main() -> int:
    if sys.version_info < (3, 10):
        print('需要 Python 3.10+。', file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent.parent
    try:
        python = prepare_environment(root, cache_directory(), sys.executable)
        os.execv(str(python), [str(python), str(root / 'cannan.py'), *sys.argv[1:]])
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
