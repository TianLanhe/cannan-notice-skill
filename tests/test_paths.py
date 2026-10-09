import importlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch


class PathTests(unittest.TestCase):
    def setUp(self):
        try:
            self.paths = importlib.import_module('cannan_cli.paths')
        except ModuleNotFoundError:
            self.fail('user defaults and title paths are not implemented')

    def test_user_defaults_are_independent_of_source(self):
        with patch.dict(os.environ, {'HOME': '/tmp/cannan-test-home'}):
            self.assertEqual(self.paths.default_profile(), Path('/tmp/cannan-test-home/.config/cannan-notice/profile.json'))
            self.assertEqual(self.paths.default_directory(), Path('/tmp/cannan-test-home/Documents/Cannan Notices'))

    def test_chinese_and_missing_titles(self):
        self.assertEqual(self.paths.notice_basename({'notice_id': 123, 'title': '家长会通知'}), 'notice-123-家长会通知')
        for title in (None, '', ' .  ', '...', []):
            self.assertEqual(self.paths.notice_basename({'notice_id': 123, 'title': title}), 'notice-123-未命名通告')

    def test_title_cannot_escape_directory(self):
        detail = {'notice_id': 123, 'title': '../../a\\b\x00\n:c*?'}
        path = self.paths.notice_folder(detail, Path('/tmp/output'))
        self.assertEqual(path.parent, Path('/tmp/output'))
        self.assertNotIn('\\', path.name)
        self.assertNotIn('\x00', path.name)
        self.assertEqual(self.paths.safe_title('e\u0301'), 'é')

    def test_utf8_budget_reserves_pdf_suffix(self):
        name = self.paths.notice_basename({'notice_id': 123, 'title': '家长通知' * 300})
        self.assertLessEqual(len((name + '-99999999999999999999.pdf').encode()), 255)
        self.assertTrue(name.startswith('notice-123-'))
        self.assertIn('家长', name)
