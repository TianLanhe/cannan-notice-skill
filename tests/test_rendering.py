import importlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pypdf import PdfWriter
from cannan_cli.client import ClientError


def scanned_pdf():
    from PIL import Image, ImageDraw
    pages = []
    for label in ('SCANNED PAGE ONE', 'SCANNED PAGE TWO'):
        image = Image.new('RGB', (600, 800), 'white')
        ImageDraw.Draw(image).text((40, 70), label, fill='black', font_size=28)
        pages.append(image)
    output = io.BytesIO()
    pages[0].save(output, 'PDF', save_all=True, append_images=pages[1:])
    for image in pages:
        image.close()
    return output.getvalue()


class RenderingTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module('cannan_cli.rendering')
        except ModuleNotFoundError:
            self.fail('local PDF rendering is not implemented')

    def test_page_ranges_are_complete_and_validated(self):
        self.assertEqual(self.module.select_pages('1,3-5,3', 5), [1, 3, 4, 5])
        self.assertEqual(self.module.select_pages(None, 2), [1, 2])
        for raw in ('0', '4', '2-1', '1,,2', 'x', '', '-1'):
            with self.subTest(raw=raw), self.assertRaises(ClientError):
                self.module.select_pages(raw, 3)

    def test_scanned_pages_render_nonblank_private_images(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / 'scan.pdf'
            pdf.write_bytes(scanned_pdf())
            result = self.module.render_pdf(pdf)
            self.assertTrue(result['complete'])
            self.assertEqual(result['total_pages'], 2)
            self.assertEqual(result['rendered_pages'], [1, 2])
            self.assertEqual(len(result['images']), 2)
            for item, name in zip(result['images'], ('page-0001.png', 'page-0002.png')):
                path = Path(item['local_path'])
                self.assertEqual(path, (Path(folder) / 'scan-pages' / name).resolve())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                with Image.open(path) as image:
                    self.assertEqual(image.format, 'PNG')
                    extrema = image.convert('RGB').getextrema()
                    self.assertLess(extrema[0][0], 255)
                    self.assertEqual(extrema[0][1], 255)
            selected = self.module.render_pdf(pdf, Path(folder) / 'selected', '2')
            self.assertEqual(selected['rendered_pages'], [2])
            self.assertEqual([p.name for p in (Path(folder) / 'selected').iterdir()], ['page-0002.png'])

    def test_invalid_or_encrypted_pdf_has_safe_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'private-filename.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.encrypt('synthetic-secret')
            output = io.BytesIO()
            writer.write(output)
            for body in (b'invalid private content', output.getvalue()):
                path.write_bytes(body)
                result = self.module.render_pdf(path)
                self.assertFalse(result['complete'])
                self.assertTrue(result['errors'])
                self.assertNotIn('synthetic-secret', str(result['errors']))
                self.assertNotIn('private content', str(result['errors']))

    def test_oversized_page_is_bounded_and_long_output_name_is_valid(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / (('通告' * 35) + '.pdf')
            writer = PdfWriter()
            writer.add_blank_page(width=3000, height=3000)
            output = io.BytesIO()
            writer.write(output)
            path.write_bytes(output.getvalue())
            result = self.module.render_pdf(path)
            self.assertTrue(result['complete'])
            item = result['images'][0]
            with Image.open(item['local_path']) as image:
                self.assertLessEqual(image.width * image.height, 20_000_000)
            self.assertLess(item['scale'], 2)
            self.assertLessEqual(len(Path(item['local_path']).parent.name.encode()), 255)

    def test_page_write_failure_keeps_earlier_page(self):
        original = self.module.write_private
        def fail_second(path, data):
            if Path(path).name == 'page-0002.png':
                raise OSError('synthetic write failure')
            original(path, data)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scan.pdf'
            path.write_bytes(scanned_pdf())
            with patch.object(self.module, 'write_private', side_effect=fail_second):
                result = self.module.render_pdf(path)
            self.assertFalse(result['complete'])
            self.assertEqual(result['rendered_pages'], [1])
            self.assertEqual(result['errors'][0]['page'], 2)
            self.assertTrue(Path(result['images'][0]['local_path']).exists())
