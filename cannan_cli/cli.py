"""Command line entry and private profile management."""
import argparse
import base64
from datetime import datetime, timezone
import getpass
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

from .attachments import collect_attachments, write_private
from .client import ClientError, CannanClient, normalize_context, parse_statuses, positive_int, sign_in
from .transport import API_HOST, CurlTransport, TransportError
from .paths import default_profile, default_directory, notice_folder

ROOT = Path(__file__).resolve().parent.parent


class _ReadableHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif not self.hidden and tag in ('br', 'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


def readable_text(content):
    parser = _ReadableHTML()
    parser.feed(str(content))
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())


def save_json(path, data):
    write_private(Path(path), (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def select_student(students, index):
    if not students:
        raise ClientError('没有可用学生。')
    if len(students) > 1 and index is None:
        raise ClientError('登录包含多个学生，请用 --student-index（从 1 开始）明确选择。')
    index = 1 if index is None else positive_int(index, 'student-index')
    if index > len(students):
        raise ClientError('student-index 超出学生列表范围。')
    return normalize_context(students[index - 1])


def context_from_har(path, student_index=None):
    try:
        capture = json.loads(Path(path).read_text())
        entries = capture['log']['entries']
    except (ValueError, KeyError, TypeError):
        raise ClientError('HAR 格式不正确。') from None
    contexts = []
    for entry in entries:
        request = entry.get('request', {})
        u = urlsplit(request.get('url', ''))
        if u.hostname != API_HOST:
            continue
        if u.path == '/api/signIn':
            try:
                content = entry['response']['content']
                text = content.get('text', '')
                if content.get('encoding') == 'base64':
                    text = base64.b64decode(text)
                data = json.loads(text)
                students = data['data']['student_list']
                if data.get('code') in (200, '200') and students:
                    language = parse_qs(u.query).get('language_code', ['zh_HK'])[0]
                    return select_student([dict(s, language_code=language) for s in students], student_index)
            except (ValueError, KeyError, TypeError):
                continue
        if u.path == '/api/listNotice':
            q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
            try:
                context = normalize_context(q)
                if context not in contexts:
                    contexts.append(context)
            except ClientError:
                continue
    return select_student(contexts, student_index)


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--profile', default=argparse.SUPPRESS, help='私有配置路径；默认 ~/.config/cannan-notice/profile.json')
    common.add_argument('--proxy', default=argparse.SUPPRESS, help='显式 HTTP/SOCKS 代理 URL')
    common.add_argument('--ca-bundle', default=argparse.SUPPRESS, help='额外 CA PEM（保留 TLS 校验）')
    common.add_argument('--resolve', action='append', default=argparse.SUPPRESS, metavar='HOST=IP', help='显式临时解析，可重复；不关闭 TLS 校验')
    common.add_argument('--timeout', type=float, default=argparse.SUPPRESS, help='每次请求超时秒数，默认 25')
    common.add_argument('--max-bytes', type=int, default=argparse.SUPPRESS, help='响应/附件上限，默认 20 MiB')
    parser = argparse.ArgumentParser(description='迦南通告列表、详情与附件客户端', parents=[common])
    subs = parser.add_subparsers(dest='command', required=True)
    login = subs.add_parser('login', parents=[common], help='登录并保存学生上下文，不保存密码')
    login.add_argument('--account', help='账号；省略时交互输入')
    login.add_argument('--student-index', type=int, help='多学生时必须指定，索引从 1 开始')
    login.add_argument('--language', choices=['zh_HK', 'en_US', 'zh_CN'], default='zh_HK')
    imp = subs.add_parser('import-profile', parents=[common], help='从自己的 HAR 导入上下文，不需重新登录')
    imp.add_argument('--har', required=True)
    imp.add_argument('--student-index', type=int)
    listing = subs.add_parser('list', parents=[common], help='按状态完整分页，输出 JSON')
    sync = subs.add_parser('sync', parents=[common], help='批量读取详情、下载附件并提取 PDF 文本')
    for sub in (listing, sync):
        sub.add_argument('--status', action='append', help='unread / unreplied / all；可重复或逗号分隔，默认 all')
        sub.add_argument('--page-size', type=int, default=20)
        sub.add_argument('--output', help='JSON 保存路径；list 默认 stdout，sync 默认目录/index.json')
    sync.add_argument('--directory', default=str(default_directory()), help='附件保存目录；默认 ~/Documents/Cannan Notices/')
    sync.add_argument('--limit', type=int, help='仅处理前 N 条，结果明确标为 limited')
    detail = subs.add_parser('detail', parents=[common], help='按 ID 读取详情（更新阅读时间）')
    detail.add_argument('notice_id', type=int)
    detail.add_argument('--output', help='JSON 保存路径；省略时 stdout')
    download = subs.add_parser('download', parents=[common], help='读取一条通告并下载全部附件（更新阅读时间）')
    download.add_argument('notice_id', type=int)
    download.add_argument('--directory', default=str(default_directory()), help='附件保存目录；默认 ~/Documents/Cannan Notices/')
    download.add_argument('--output', help='JSON 保存路径；默认通知目录/notice.json')
    return parser


def network_options(profile, args):
    options = dict(profile.get('network', {}))
    for field in ('proxy', 'ca_bundle', 'timeout', 'max_bytes'):
        if hasattr(args, field):
            options[field] = getattr(args, field)
    if hasattr(args, 'resolve'):
        resolve = dict(options.get('resolve', {}))
        for entry in args.resolve:
            if '=' not in entry:
                raise ClientError('--resolve 的格式应为 HOST=IP。')
            host, address = entry.split('=', 1)
            resolve[host] = address
        options['resolve'] = resolve
    allowed = {'proxy', 'ca_bundle', 'resolve', 'timeout', 'max_bytes', 'allowed_hosts'}
    if set(options) - allowed:
        raise ClientError('network 配置包含不支持的字段。')
    return options


def emit(data, path=None):
    if path:
        save_json(path, data)
        print(json.dumps({'saved': str(Path(path).resolve())}, ensure_ascii=False))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def process_notice(client, transport, notice_id: int, directory: Path) -> dict:
    detail = client.detail(notice_id)
    attachments = collect_attachments(transport, detail, directory)
    texts = [item['text'] for item in attachments if item.get('text')]
    if detail.get('content'):
        texts.insert(0, readable_text(detail['content']))
    text = '\n\n'.join(texts)
    errors = []
    text_complete = bool(text.strip())
    text_status = 'ok' if text_complete else 'no_body'
    for item in attachments:
        if item['status'] in ('error', 'dependency_missing'):
            message = item.get('error') or ('附件 PDF 提取依赖缺失。' if item['status'] == 'dependency_missing' else '附件处理失败。')
            errors.append({'notice_id': notice_id, 'attachment_index': item['index'], 'error': message})
        if item['status'] != 'ok':
            text_complete = False
            text_status = 'partial' if text.strip() else item['status']
    return dict(detail=detail, attachments=attachments, extracted_text=text,
                text_status=text_status, sync_status='error' if errors else 'ok',
                errors=errors, complete=not errors, text_complete=text_complete)


def completion_code(result: dict) -> int:
    if result['errors']:
        return 2
    return 0 if result['complete'] and result['text_complete'] else 3


def sync_notices(client, transport, result, directory, limit=None):
    if limit is not None:
        limit = positive_int(limit, 'limit')
    selected = result['notices'] if limit is None else result['notices'][:limit]
    result.update(list_complete=True, reading_updates_timestamp=True, processed=0,
                  limited=len(selected) < len(result['notices']), text_complete=True)
    for row in result['notices']:
        row['sync_status'] = 'not_processed'
    for row in selected:
        try:
            processed = process_notice(client, transport, row['notice_id'], directory)
            row.update(processed)
            result['errors'].extend(processed['errors'])
            result['text_complete'] = result['text_complete'] and processed['text_complete']
        except (ClientError, TransportError, OSError) as error:
            row['sync_status'] = 'error'
            result['errors'].append({'notice_id': row['notice_id'],
                                     'error': str(error) if isinstance(error, (ClientError, TransportError)) else '文件操作失败。'})
            result['text_complete'] = False
        result['processed'] += 1
        print(f'已处理 {result["processed"]}/{len(selected)} 条', file=sys.stderr)
    result['complete'] = not result['errors'] and not result['limited']
    if result['limited']:
        result['text_complete'] = False
    return result


def main(argv=None):
    args = build_parser().parse_args(argv)
    path = Path(getattr(args, 'profile', default_profile())).expanduser()
    try:
        if path.exists():
            profile = json.loads(path.read_text())
            if not isinstance(profile, dict):
                raise ClientError('profile 必须是 JSON 对象。')
        else:
            profile = {}
        options = network_options(profile, args)
        transport = CurlTransport(**options)
        if args.command in ('login', 'import-profile'):
            if args.command == 'login':
                account = args.account or input('账号：').strip()
                password = os.environ.get('CANNAN_PASSWORD') or getpass.getpass('密码：')
                students = sign_in(transport, account, password, args.language)
                context = select_student([dict(s, language_code=args.language) for s in students], args.student_index)
                del password
            else:
                context = context_from_har(args.har, args.student_index)
            save_json(path, {'context': context, 'network': options})
            print(json.dumps({'profile_saved': str(path.resolve()), 'password_saved': False}, ensure_ascii=False))
            return 0
        if 'context' not in profile:
            raise ClientError('尚无学生上下文；先运行 login 或 import-profile。')
        client = CannanClient(transport, profile['context'])
        if args.command == 'list':
            result = client.list_notices(parse_statuses(args.status), args.page_size)
            emit(result, args.output)
            return 0
        if args.command == 'detail':
            result = {'generated_at': datetime.now(timezone.utc).isoformat(),
                      'reading_updates_timestamp': True, 'data': client.detail(args.notice_id)}
            emit(result, args.output)
            return 0
        if args.command == 'download':
            directory = Path(args.directory).expanduser().resolve()
            result = process_notice(client, transport, args.notice_id, directory)
            result.update(generated_at=datetime.now(timezone.utc).isoformat(), reading_updates_timestamp=True)
            output = args.output or notice_folder(result['detail'], directory) / 'notice.json'
            emit(result, output)
            return completion_code(result)
        result = client.list_notices(parse_statuses(args.status), args.page_size)
        result = sync_notices(client, transport, result, Path(args.directory).expanduser().resolve(), args.limit)
        output = args.output or str(Path(args.directory).expanduser().resolve() / 'index.json')
        emit(result, output)
        return completion_code(result)
    except (ClientError, TransportError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, EOFError):
        print('本地文件、配置或输入格式错误；未输出敏感返回内容。', file=sys.stderr)
        return 2
