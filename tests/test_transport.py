import importlib
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


class TransportTests(unittest.TestCase):
    def setUp(self):
        try:
            self.mod = importlib.import_module('cannan_cli.transport')
        except ModuleNotFoundError:
            self.fail('transport safety and HTTPS client not implemented')

    def test_unicode_url_preserves_existing_escapes(self):
        self.assertEqual(
            self.mod.safe_url('https://apps.cannan.edu.hk/中文 a%20b.pdf', {'apps.cannan.edu.hk'}),
            'https://apps.cannan.edu.hk/%E4%B8%AD%E6%96%87%20a%20b.pdf')

    def test_rejects_non_https_credentials_and_other_host(self):
        for url in ('http://apps.cannan.edu.hk/a', 'https://user:secret@apps.cannan.edu.hk/a',
                    'https://other.example/a', 'https://apps.cannan.edu.hk:444/a'):
            with self.subTest(url=url), self.assertRaises(self.mod.TransportError):
                self.mod.safe_url(url, {'apps.cannan.edu.hk'})

    def test_curl_keeps_tls_validation_and_parses_response(self):
        def fake_run(args, **kwargs):
            self.assertNotIn('-k', args)
            self.assertNotIn('--insecure', args)
            self.assertNotIn('secret', ' '.join(args))
            self.assertIn('url = "https://apps.cannan.edu.hk/api/test?password=secret"', kwargs['input'])
            self.assertEqual(args[args.index('--cacert') + 1], '/tmp/test-ca.pem')
            self.assertEqual(args[args.index('--resolve') + 1], 'apps.cannan.edu.hk:443:192.0.2.1')
            Path(args[args.index('--output') + 1]).write_bytes(b'{"ok":true}')
            Path(args[args.index('--dump-header') + 1]).write_text('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n')
            return subprocess.CompletedProcess(args, 0, '200', '')
        t = self.mod.CurlTransport(ca_bundle='/tmp/test-ca.pem', resolve={'apps.cannan.edu.hk': '192.0.2.1'})
        with patch('subprocess.run', fake_run):
            response = t.request('GET', 'https://apps.cannan.edu.hk/api/test', {'password': 'secret'})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b'{"ok":true}')
        self.assertEqual(response.headers['content-type'], 'application/json')

    def test_network_failure_never_echoes_sensitive_url(self):
        bad = subprocess.CompletedProcess([], 60, '', 'failure password=secret student_id=123')
        with patch('subprocess.run', return_value=bad), self.assertRaises(self.mod.TransportError) as ctx:
            self.mod.CurlTransport().request('GET', 'https://apps.cannan.edu.hk/api/test', {'password': 'secret'})
        self.assertNotIn('secret', str(ctx.exception))
        self.assertNotIn('123', str(ctx.exception))
        self.assertIn('60', str(ctx.exception))

    def test_response_size_limit_is_enforced(self):
        def fake_run(args, **kwargs):
            Path(args[args.index('--output') + 1]).write_bytes(b'12345')
            Path(args[args.index('--dump-header') + 1]).write_text('HTTP/1.1 200 OK\n')
            return subprocess.CompletedProcess(args, 0, '200', '')
        with patch('subprocess.run', fake_run), self.assertRaises(self.mod.TransportError):
            self.mod.CurlTransport(max_bytes=4).request('GET', 'https://apps.cannan.edu.hk/a')

    def test_resolve_requires_ip_and_valid_network_limits(self):
        for kwargs in ({'resolve': {'apps.cannan.edu.hk': 'not-an-ip'}}, {'timeout': 0}, {'max_bytes': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(self.mod.TransportError):
                self.mod.CurlTransport(**kwargs)
