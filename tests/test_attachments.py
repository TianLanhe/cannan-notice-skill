import importlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from cannan_cli.transport import HttpResponse


def pdf_bytes(text=True):
    w=PdfWriter(); page=w.add_blank_page(width=600,height=800)
    if text:
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 30 700 Td (Example notice) Tj ET')
        page[NameObject('/Contents')]=w._add_object(stream)
    out=io.BytesIO();w.write(out);return out.getvalue()


class FakeTransport:
    allowed_hosts={'apps.cannan.edu.hk'}
    def __init__(self,redirect=None):self.redirect=redirect
    def request(self,method,url,params=None):
        if '中文' in url or ' ' in url:raise AssertionError('URL not encoded')
        if self.redirect:return HttpResponse(302,{'location':self.redirect},b'')
        return HttpResponse(200,{'content-type':'application/pdf'},pdf_bytes())


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        try:self.m=importlib.import_module('cannan_cli.attachments')
        except ModuleNotFoundError:self.fail('attachment collection not implemented')

    def test_pdf_text_and_safe_file_names(self):
        d={'notice_id':1,'attachment_list':[{'title':'../../outside.pdf','url':'https://apps.cannan.edu.hk/中文 a.pdf','notice_attachment_id':3}]}
        with tempfile.TemporaryDirectory() as folder:
            r=self.m.collect_attachments(FakeTransport(),d,Path(folder))
            self.assertEqual(r[0]['status'],'ok')
            self.assertIn('Example notice',r[0]['text'])
            p=Path(r[0]['local_path']);self.assertEqual(p.parent,Path(folder)/'notice-1')
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            self.assertNotIn('outside',p.name)

    def test_no_text_marks_ocr(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'blank.pdf';p.write_bytes(pdf_bytes(False))
            r=self.m.extract_pdf(p)
            self.assertEqual(r['status'],'needs_ocr');self.assertEqual(r['pages'],1)

    def test_mixed_pdf_marks_missing_pages_and_preserves_available_text(self):
        writer=PdfWriter();writer.append(io.BytesIO(pdf_bytes()))
        writer.add_blank_page(width=600,height=800)
        out=io.BytesIO();writer.write(out)
        class Mixed(FakeTransport):
            def request(self,*args,**kwargs):
                return HttpResponse(200,{'content-type':'application/pdf'},out.getvalue())
        detail={'notice_id':1,'attachment_list':[{'url':'https://apps.cannan.edu.hk/mixed.pdf'}]}
        with tempfile.TemporaryDirectory() as folder:
            item=self.m.collect_attachments(Mixed(),detail,Path(folder))[0]
            self.assertEqual(item['status'],'partial')
            self.assertEqual(item['pages'],2)
            self.assertEqual(item['pages_without_text'],[2])
            self.assertIn('Example notice',item['text'])
            self.assertEqual(Path(item['text_path']).read_text(),item['text'])
            self.assertTrue(Path(item['local_path']).exists())

    def test_missing_dependency_is_reported(self):
        import sys
        with patch.dict(sys.modules,{'pypdf':None}):
            r=self.m.extract_pdf(Path('/tmp/unused.pdf'))
        self.assertEqual(r['status'],'dependency_missing')

    def test_external_redirect_is_rejected(self):
        d={'notice_id':1,'attachment_list':[{'title':'x','url':'https://apps.cannan.edu.hk/a.pdf'}]}
        with tempfile.TemporaryDirectory() as folder:
            r=self.m.collect_attachments(FakeTransport('https://other.example/a.pdf'),d,Path(folder))
            self.assertEqual(r[0]['status'],'error');self.assertNotIn('local_path',r[0])

    def test_redirect_loop_is_bounded(self):
        d={'notice_id':1,'attachment_list':[{'title':'x','url':'https://apps.cannan.edu.hk/a.pdf'}]}
        with tempfile.TemporaryDirectory() as folder:
            r=self.m.collect_attachments(FakeTransport('/a.pdf'),d,Path(folder))
            self.assertEqual(r[0]['status'],'error')

    def test_non_pdf_response_cannot_masquerade_as_pdf(self):
        class Bad(FakeTransport):
            def request(self,*args,**kwargs):return HttpResponse(200,{'content-type':'text/html'},b'<html>error</html>')
        d={'notice_id':1,'attachment_list':[{'title':'x','url':'https://apps.cannan.edu.hk/a.pdf'}]}
        with tempfile.TemporaryDirectory() as folder:
            r=self.m.collect_attachments(Bad(),d,Path(folder))
            self.assertEqual(r[0]['status'],'error')
