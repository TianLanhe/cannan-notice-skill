"""App protocol, status unions and pagination integrity."""
from datetime import datetime, timezone
import json

from .transport import API_HOST, TransportError

BASE = f'https://{API_HOST}/api/'
STATUS_FILTERS = {'unread': ('0', '0'), 'unreplied': ('1', '0'), 'all': ('', '')}
CONTEXT_IDS = ('student_id', 'school_year_id', 'school_id', 'grade_id', 'class_id')


class ClientError(RuntimeError):
    pass


def positive_int(value, label='ID'):
    if isinstance(value, bool) or not (isinstance(value, int) or isinstance(value, str) and value.isdecimal()):
        raise ClientError(f'{label} 必须是正整数。')
    value = int(value)
    if value <= 0:
        raise ClientError(f'{label} 必须是正整数。')
    return value


def normalize_context(context):
    if not isinstance(context, dict):
        raise ClientError('学生上下文格式不正确。')
    try:
        result = {k: positive_int(context[k], k) for k in CONTEXT_IDS}
    except KeyError:
        raise ClientError('学生上下文缺少必要字段。') from None
    language = context.get('language_code', 'zh_HK')
    if language not in ('zh_HK', 'en_US', 'zh_CN'):
        raise ClientError('不支持该语言代码。')
    return dict(result, language_code=language)


def parse_statuses(raw):
    result = []
    for item in raw or ['all']:
        if not isinstance(item, str):
            raise ClientError('状态必须是字符串。')
        for state in item.split(','):
            state = state.strip()
            if state not in STATUS_FILTERS:
                raise ClientError('状态只支持 unread、unreplied、all。')
            if state not in result:
                result.append(state)
    return result


def api_data(transport, method, endpoint, params):
    response = transport.request(method, BASE + endpoint, params)
    if not 200 <= response.status < 300:
        raise ClientError(f'接口 HTTP 状态为 {response.status}。')
    try:
        result = json.loads(response.body)
    except (ValueError, UnicodeError):
        raise ClientError('接口返回的内容不是有效 JSON。') from None
    if not isinstance(result, dict) or result.get('code') not in (200, '200'):
        raise ClientError('接口返回业务错误；请检查账号或学生上下文。')
    if 'data' not in result:
        raise ClientError('接口响应缺少 data。')
    return result['data']


def sign_in(transport, account, password, language='zh_HK'):
    if not account or not password:
        raise ClientError('账号和密码不能为空。')
    data = api_data(transport, 'POST', 'signIn', {
        'account_no': account, 'password': password, 'is_delete_user_push_token': 0,
        'language_code': language})
    if not isinstance(data, dict) or not isinstance(data.get('student_list'), list) or not data['student_list']:
        raise ClientError('登录响应中没有可用学生。')
    for student in data['student_list']:
        normalize_context(dict(student, language_code=language))
    return data['student_list']


class CannanClient:
    def __init__(self, transport, context):
        self.transport = transport
        self.context = normalize_context(context)
        self._known = set()
        self._all_loaded = False

    def _list_status(self, status, page_size):
        reply, confirmed = STATUS_FILTERS[status]
        rows, seen, expected_total, expected_last = [], set(), None, None
        page = 1
        while True:
            data = api_data(self.transport, 'GET', 'listNotice', dict(
                self.context, has_reply_slip=reply, is_confirmed=confirmed,
                current_page=page, page_size=page_size))
            if not isinstance(data, dict) or not isinstance(data.get('data'), list):
                raise ClientError('列表响应结构不正确。')
            current, last, total = data.get('current_page'), data.get('last_page'), data.get('total')
            if (any(not isinstance(x, int) or isinstance(x, bool) for x in (current, last, total))
                    or current != page or total < 0 or not 1 <= last <= 10000):
                raise ClientError('分页页码或总数异常，无法保证完整性。')
            if expected_total is None:
                expected_total, expected_last = total, last
            elif (total, last) != (expected_total, expected_last):
                raise ClientError('采集期间列表总数改变，请重新查询。')
            for row in data['data']:
                if not isinstance(row, dict):
                    raise ClientError('通告条目结构不正确。')
                identity = positive_int(row.get('notice_id'), 'notice_id')
                if identity in seen:
                    raise ClientError('列表出现重复条目或重复页，无法保证完整性。')
                seen.add(identity)
                rows.append(dict(row, notice_id=identity))
            if page == last:
                break
            if not data['data']:
                raise ClientError('列表提前返回空页，无法保证完整性。')
            page += 1
        if len(rows) != expected_total:
            raise ClientError('唯一条目数与服务端 total 不一致，结果不完整。')
        return rows, {'count': len(rows), 'total': expected_total, 'pages': page}

    def list_notices(self, statuses=None, page_size=20):
        states = parse_statuses(statuses)
        page_size = positive_int(page_size, 'page_size')
        if page_size > 1000:
            raise ClientError('page_size 不得超过 1000。')
        notices, stats = {}, {}
        for state in states:
            rows, stats[state] = self._list_status(state, page_size)
            for row in rows:
                identity = row['notice_id']
                if identity not in notices:
                    notices[identity] = dict(row, matched_statuses=[])
                notices[identity]['matched_statuses'].append(state)
            if state == 'all':
                self._all_loaded = True
        self._known.update(notices)
        return {'generated_at': datetime.now(timezone.utc).isoformat(),
                'student_context': dict(self.context), 'requested_statuses': states,
                'by_status': stats, 'notices': list(notices.values()), 'errors': [], 'complete': True}

    def detail(self, notice_id):
        identity = positive_int(notice_id, 'notice_id')
        if identity not in self._known and not self._all_loaded:
            self.list_notices(['all'])
        if identity not in self._known:
            raise ClientError('该通告不在当前学生的已取得列表中。')
        data = api_data(self.transport, 'GET', 'getNotice', dict(self.context, notice_id=identity))
        if not isinstance(data, dict) or data.get('notice_id') != identity:
            raise ClientError('详情响应与请求的通告不一致。')
        return data
