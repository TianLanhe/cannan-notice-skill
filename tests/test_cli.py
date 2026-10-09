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
            code=self.m.main(['--profile',str(self.profile),*args])
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
