import importlib
import json
import unittest
from urllib.parse import urlsplit
from cannan_cli.transport import HttpResponse

CONTEXT = dict(student_id=10, school_year_id=3, school_id=2, grade_id=4, class_id=5, language_code='zh_HK')


def notice(n, reply=False, confirmed=False):
    return dict(notice_id=n, title='Example', content=None, has_reply_slip=reply,
                has_attachment=False, read_date_time='2026-01-01',
                confirmed_date_time='2026-01-02' if confirmed else None)


class FakeTransport:
    def __init__(self, corrupt=None):
        self.corrupt = corrupt
        self.details = []
        self.datasets = {('', ''): [notice(i) for i in range(1, 30)],
                         ('0', '0'): [notice(1), notice(2)], ('1', '0'): [notice(3, True)]}
    def request(self, method, url, params=None):
        path = urlsplit(url).path
        if path.endswith('/signIn'):
            if params.get('is_delete_user_push_token') != 0:
                raise AssertionError('Login must not delete phone push token')
            d = {'student_list': [dict(CONTEXT, account_no='hidden')]}
        elif path.endswith('/getNotice'):
            self.details.append(params['notice_id'])
            d = notice(params['notice_id'])
        else:
            self.assert_context(params)
            rows = self.datasets[(str(params['has_reply_slip']), str(params['is_confirmed']))]
            page = int(params['current_page']); size = int(params['page_size'])
            d = dict(current_page=page, last_page=(len(rows)+size-1)//size, total=len(rows), per_page=size,
                     data=rows[(page-1)*size:page*size])
            if self.corrupt == 'repeat' and page == 2: d['data'] = rows[:size]
            if self.corrupt == 'total': d['total'] += 1
            if self.corrupt == 'page': d['current_page'] = 99
        code = 401 if self.corrupt == 'business' else 200
        return HttpResponse(200, {}, json.dumps({'code':code,'data':d,'message':'hidden'}).encode())
    def assert_context(self, p):
        for k in ('student_id','school_year_id','school_id','grade_id','class_id','language_code'):
            if p[k] != CONTEXT[k]: raise AssertionError('Incorrect student context')


class ClientTests(unittest.TestCase):
    def setUp(self):
        try: self.m = importlib.import_module('cannan_cli.client')
        except ModuleNotFoundError: self.fail('status pagination client not implemented')

    def test_all_fetches_both_pages_and_checks_total(self):
        d = self.m.CannanClient(FakeTransport(), CONTEXT).list_notices(['all'])
        self.assertEqual(len(d['notices']),29)
        self.assertEqual(d['by_status']['all'],{'count':29,'total':29,'pages':2})
        self.assertTrue(d['complete'])

    def test_batch_statuses_are_union_and_read_time_does_not_filter_unread(self):
        d = self.m.CannanClient(FakeTransport(), CONTEXT).list_notices(['unread,unreplied','unread'])
        self.assertEqual([x['notice_id'] for x in d['notices']],[1,2,3])
        self.assertEqual(d['notices'][0]['matched_statuses'],['unread'])
        self.assertEqual(d['notices'][2]['matched_statuses'],['unreplied'])
        self.assertEqual(d['requested_statuses'],['unread','unreplied'])

    def test_all_plus_status_deduplicates_and_preserves_membership(self):
        d = self.m.CannanClient(FakeTransport(), CONTEXT).list_notices(['all','unread'])
        self.assertEqual(len(d['notices']),29)
        self.assertEqual(d['notices'][0]['matched_statuses'],['all','unread'])
        self.assertEqual(d['notices'][-1]['matched_statuses'],['all'])

    def test_bad_pagination_and_business_error_fail_not_partial_success(self):
        for issue in ('repeat','total','page','business'):
            with self.subTest(issue=issue), self.assertRaises(self.m.ClientError):
                self.m.CannanClient(FakeTransport(issue), CONTEXT).list_notices(['all'])

    def test_detail_requires_membership_and_calls_once(self):
        t = FakeTransport(); c = self.m.CannanClient(t,CONTEXT)
        self.assertEqual(c.detail(1)['notice_id'],1)
        self.assertEqual(t.details,[1])
        with self.assertRaises(self.m.ClientError): c.detail(999)
        self.assertEqual(t.details,[1])

    def test_login_does_not_delete_push_tokens_or_persist_password(self):
        students = self.m.sign_in(FakeTransport(),'user','secret')
        self.assertEqual(students[0]['student_id'],10)
        self.assertNotIn('secret',json.dumps(students))

    def test_invalid_context_status_and_page_size(self):
        for bad in ('bad','unread,,unreplied'):
            with self.assertRaises(self.m.ClientError): self.m.parse_statuses([bad])
        with self.assertRaises(self.m.ClientError): self.m.CannanClient(FakeTransport(),dict(CONTEXT,student_id=-1))
        with self.assertRaises(self.m.ClientError): self.m.CannanClient(FakeTransport(),CONTEXT).list_notices(['all'],0)
