import contextlib
import importlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_client import CONTEXT, FakeTransport
from cannan_cli.transport import TransportError
from cannan_cli.transport import HttpResponse
from test_attachments import pdf_bytes


class CliTests(unittest.TestCase):
    def setUp(self):
        try:self.m=importlib.import_module('cannan_cli.cli')
        except ModuleNotFoundError:self.fail('CLI not implemented')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.profile=Path(self.temp.name)/'profile.json'
        self.profile.write_text(json.dumps({'context':CONTEXT,'network':{}}))

    def run_cli(self,*args,transport=None):
        out,err=io.StringIO(),io.StringIO()
        with patch.object(self.m,'CurlTransport',return_value=transport or FakeTransport()),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            try:
                code=self.m.main(['--profile',str(self.profile),*args])
            except SystemExit:
                self.fail('requested CLI behavior is not implemented')
        return code,out.getvalue(),err.getvalue()

    def test_default_all_is_complete_json(self):
        code,out,err=self.run_cli('list')
        self.assertEqual(code,0);d=json.loads(out);self.assertEqual(len(d['notices']),29)
        self.assertEqual(d['requested_statuses'],['all']);self.assertEqual(err,'')

    def test_repeated_and_comma_status_options(self):
        code,out,_=self.run_cli('list','--status','unread,unreplied','--status','unread')
        self.assertEqual(code,0);self.assertEqual(len(json.loads(out)['notices']),3)

    def test_login_password_is_never_saved_or_printed(self):
        with patch.dict(os.environ,{'CANNAN_PASSWORD':'my-secret'}):
            code,out,err=self.run_cli('login','--account','test-account')
        self.assertEqual(code,0)
        self.assertNotIn('my-secret',self.profile.read_text()+out+err)
        self.assertEqual(self.profile.stat().st_mode & 0o777,0o600)
        self.assertEqual(json.loads(self.profile.read_text())['context'],CONTEXT)

    def test_import_har_profile(self):
        capture=Path(self.temp.name)/'capture.har'
        capture.write_text(json.dumps({'log':{'entries':[{'request':{'url':'https://apps.cannan.edu.hk/api/listNotice?student_id=10&school_year_id=3&school_id=2&grade_id=4&class_id=5&language_code=zh_HK'}}]}}))
        code,out,_=self.run_cli('import-profile','--har',str(capture))
        self.assertEqual(code,0);self.assertEqual(json.loads(self.profile.read_text())['context'],CONTEXT)

    def test_multistudent_requires_selection(self):
        class Multi(FakeTransport):
            def request(self,method,url,params=None):
                response=super().request(method,url,params)
                if url.endswith('/signIn'):
                    d=json.loads(response.body);d['data']['student_list'].append(dict(CONTEXT,student_id=11))
                    response.body=json.dumps(d).encode()
                return response
        before=self.profile.read_text()
        with patch.dict(os.environ,{'CANNAN_PASSWORD':'secret'}):
            code,out,err=self.run_cli('login','--account','user',transport=Multi())
        self.assertEqual(code,2);self.assertEqual(self.profile.read_text(),before)
        self.assertNotIn('secret',err)

    def test_detail_verifies_membership(self):
        code,out,_=self.run_cli('detail','1')
        self.assertEqual(code,0);self.assertEqual(json.loads(out)['data']['notice_id'],1)
        code,out,_=self.run_cli('detail','999')
        self.assertEqual(code,2)

    def test_sync_reports_partial_failures_and_preserves_json(self):
        class Fail(FakeTransport):
            def request(self,method,url,params=None):
                if url.endswith('/getNotice') and params['notice_id']==2:raise TransportError('HTTPS 请求失败。')
                return super().request(method,url,params)
        folder=Path(self.temp.name)/'data'
        code,out,_=self.run_cli('sync','--status','unread','--directory',str(folder),transport=Fail())
        self.assertEqual(code,2)
        d=json.loads((folder/'index.json').read_text());self.assertFalse(d['complete'])
        self.assertEqual(len(d['errors']),1);self.assertEqual(d['processed'],2)
        self.assertEqual((folder/'index.json').stat().st_mode & 0o777,0o600)

    def test_sync_limit_is_explicit(self):
        folder=Path(self.temp.name)/'data'
        code,_,_=self.run_cli('sync','--status','all','--limit','1','--directory',str(folder))
        d=json.loads((folder/'index.json').read_text());self.assertEqual(code,3)
        self.assertTrue(d['limited']);self.assertFalse(d['complete']);self.assertEqual(d['processed'],1)

    def test_html_body_is_readable_text_not_scripts(self):
        class Html(FakeTransport):
            def request(self,method,url,params=None):
                r=super().request(method,url,params)
                if url.endswith('/getNotice'):
                    d=json.loads(r.body);d['data']['content']='<p>您好<br>公告 &amp; 提醒</p><script>hidden()</script>'
                    r.body=json.dumps(d).encode()
                return r
        folder=Path(self.temp.name)/'html'
        code,_,_=self.run_cli('sync','--status','unreplied','--directory',str(folder),transport=Html())
        d=json.loads((folder/'index.json').read_text())
        self.assertEqual(code,0)
        text=d['notices'][0]['extracted_text']
        self.assertEqual(text,'您好\n公告 & 提醒')
        self.assertTrue(d['text_complete'])

    def test_absent_body_is_not_claimed_as_complete_text(self):
        folder=Path(self.temp.name)/'empty'
        code,_,_=self.run_cli('sync','--status','unreplied','--directory',str(folder))
        d=json.loads((folder/'index.json').read_text())
        self.assertEqual(code,3)
        self.assertFalse(d['text_complete'])
        self.assertEqual(d['notices'][0]['text_status'],'no_body')

    def test_scan_pdf_returns_partial_exit_code_and_retains_result(self):
        class Scan(FakeTransport):
            def request(self,method,url,params=None):
                if url.endswith('/scan.pdf'):
                    return HttpResponse(200,{'content-type':'application/pdf'},pdf_bytes(False))
                r=super().request(method,url,params)
                if url.endswith('/getNotice'):
                    d=json.loads(r.body);d['data']['content']=None
                    d['data']['attachment_list']=[{'url':'https://apps.cannan.edu.hk/scan.pdf'}]
                    r.body=json.dumps(d).encode()
                return r
        folder=Path(self.temp.name)/'scan'
        code,_,_=self.run_cli('sync','--status','unreplied','--directory',str(folder),transport=Scan())
        self.assertEqual(code,3)
        result=json.loads((folder/'index.json').read_text())
        self.assertTrue(result['complete'])
        self.assertFalse(result['text_complete'])
        self.assertEqual(result['errors'],[])
        item=result['notices'][0]['attachments'][0]
        self.assertEqual(item['status'],'needs_ocr')
        self.assertEqual(item['pages_without_text'],[1])
        self.assertTrue(Path(item['local_path']).exists())

    def test_missing_user_profile_does_not_fall_back_to_source(self):
        source = Path(self.temp.name) / 'source'
        legacy = source / '.local' / 'profile.json'
        legacy.parent.mkdir(parents=True)
        legacy.write_text(self.profile.read_text())
        with patch.dict(os.environ, {'HOME': str(Path(self.temp.name) / 'empty-home')}), patch.object(self.m, 'ROOT', source), patch.object(self.m, 'CurlTransport', return_value=FakeTransport()), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.m.main(['list']), 2)

    def test_default_login_writes_user_profile(self):
        home = Path(self.temp.name) / 'new-home'
        with patch.dict(os.environ, {'HOME': str(home), 'CANNAN_PASSWORD': 'synthetic-secret'}), patch.object(self.m, 'ROOT', Path(self.temp.name) / 'source'), patch.object(self.m, 'CurlTransport', return_value=FakeTransport()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.m.main(['login', '--account', 'synthetic-account']), 0)
        profile = home / '.config' / 'cannan-notice' / 'profile.json'
        self.assertTrue(profile.exists())
        self.assertNotIn('synthetic-secret', profile.read_text())

    def attachment_transport(self, body=None, image=False):
        class Attachments(FakeTransport):
            def request(self, method, url, params=None):
                if url.endswith('/attachment.pdf'):
                    return HttpResponse(200, {'content-type': 'application/pdf'}, body if body is not None else pdf_bytes())
                if url.endswith('/attachment.jpg'):
                    return HttpResponse(200, {'content-type': 'image/jpeg'}, b'image-original')
                response = super().request(method, url, params)
                if url.endswith('/getNotice'):
                    data = json.loads(response.body)
                    data['data']['attachment_list'] = [{'url': 'https://apps.cannan.edu.hk/attachment.' + ('jpg' if image else 'pdf')}]
                    response.body = json.dumps(data).encode()
                return response
        return Attachments()

    def test_download_single_notice_keeps_batch_index(self):
        directory = Path(self.temp.name) / 'download'
        directory.mkdir()
        (directory / 'index.json').write_text('KEEP')
        transport = self.attachment_transport()
        code, _, _ = self.run_cli('download', '1', '--directory', str(directory), transport=transport)
        self.assertEqual(code, 0)
        data = json.loads((directory / 'notice-1-Example' / 'notice.json').read_text())
        self.assertTrue(data['complete'])
        self.assertTrue(data['text_complete'])
        self.assertTrue(Path(data['attachments'][0]['collection_path']).exists())
        self.assertEqual(transport.details, [1])
        self.assertEqual((directory / 'index.json').read_text(), 'KEEP')
        code, _, _ = self.run_cli('download', '999', '--directory', str(directory), transport=transport)
        self.assertEqual(code, 2)
        self.assertEqual(transport.details, [1])

    def test_download_defaults_to_user_documents(self):
        home = Path(self.temp.name) / 'download-home'
        with patch.dict(os.environ, {'HOME': str(home)}):
            code, _, _ = self.run_cli('download', '1', transport=self.attachment_transport())
        self.assertEqual(code, 0)
        self.assertTrue((home / 'Documents' / 'Cannan Notices' / 'notice-1-Example' / 'notice.json').exists())

    def test_download_reports_visual_and_parse_states(self):
        directory = Path(self.temp.name) / 'states'
        for transport, expected in ((self.attachment_transport(pdf_bytes(False)), 3), (self.attachment_transport(image=True), 3), (self.attachment_transport(b'%PDF-1.7\ninvalid'), 2)):
            code, _, _ = self.run_cli('download', '1', '--directory', str(directory), transport=transport)
            self.assertEqual(code, expected)
            data = json.loads((directory / 'notice-1-Example' / 'notice.json').read_text())
            self.assertFalse(data['text_complete'])
            self.assertTrue(Path(data['attachments'][0]['local_path']).exists())
            if expected == 2:
                self.assertIn('解析', data['errors'][0]['error'])

    def test_sync_index_is_current_run_and_keeps_old_downloads(self):
        directory = Path(self.temp.name) / 'history'
        transport = self.attachment_transport()
        self.run_cli('sync', '--status', 'unread', '--directory', str(directory), transport=transport)
        self.run_cli('sync', '--status', 'unreplied', '--directory', str(directory), transport=transport)
        data = json.loads((directory / 'index.json').read_text())
        self.assertEqual([row['notice_id'] for row in data['notices']], [3])
        self.assertTrue((directory / 'notice-1-Example' / 'attachment-1.pdf').exists())

    def test_download_copy_failure_is_saved_as_error(self):
        import cannan_cli.attachments as module
        original_write = module.write_private
        def fail_copy(path, data):
            if Path(path).parent.name == 'pdfs':
                raise OSError('synthetic disk failure')
            return original_write(path, data)
        directory = Path(self.temp.name) / 'copy-error'
        with patch.object(module, 'write_private', side_effect=fail_copy):
            code, _, _ = self.run_cli('download', '1', '--directory', str(directory), transport=self.attachment_transport())
        self.assertEqual(code, 2)
        data = json.loads((directory / 'notice-1-Example' / 'notice.json').read_text())
        self.assertFalse(data['complete'])
        self.assertEqual(len(data['errors']), 1)
        self.assertTrue(Path(data['attachments'][0]['local_path']).exists())

    def test_render_without_profile_or_network(self):
        path = Path(self.temp.name) / 'scan.pdf'
        path.write_bytes(pdf_bytes())
        self.profile.unlink()
        out = io.StringIO()
        with patch.object(self.m, 'CurlTransport', side_effect=AssertionError('render must stay offline')), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = self.m.main(['--profile', str(self.profile), 'render', str(path), '--pages', '1'])
            except SystemExit:
                self.fail('local render command is not implemented')
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data['rendered_pages'], [1])
