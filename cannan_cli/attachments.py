"""Download only validated attachment hosts; preserve originals and text status."""
import os
import logging
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlsplit

from .client import ClientError, positive_int
from .transport import API_HOST, TransportError, safe_url
from .paths import notice_folder


def write_private(path: Path, data: bytes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.cannan-', delete=False) as file:
        temporary = Path(file.name)
        try:
            os.chmod(temporary, 0o600)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def extract_pdf(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return {'text': '', 'pages': None, 'status': 'dependency_missing'}
    logger = logging.getLogger('pypdf')
    previous_level = logger.level
    logger.setLevel(logging.CRITICAL + 1)
    try:
        reader = PdfReader(str(path))
        page_texts = [page.extract_text() or '' for page in reader.pages]
        missing = [index for index, text in enumerate(page_texts, 1) if not text.strip()]
        text = '\n\n'.join(page_texts)
        status = 'needs_ocr' if not text.strip() else ('partial' if missing else 'ok')
        return {'text': text, 'pages': len(page_texts), 'pages_without_text': missing, 'status': status}
    except Exception:
        return {'text': '', 'pages': None, 'status': 'error', 'error': 'PDF 解析失败，文件可能损坏或需要解密；原件已保留。'}
    finally:
        logger.setLevel(previous_level)


def collect_attachments(transport, detail: dict, directory: Path):
    identity = positive_int(detail.get('notice_id'), 'notice_id')
    attachments = detail.get('attachment_list') or []
    if not isinstance(attachments, list):
        raise ClientError('附件列表格式不正确。')
    folder = notice_folder(detail, directory)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    pdf_ordinal = 0
    hosts = set(getattr(transport, 'allowed_hosts', {API_HOST}))
    for index, attachment in enumerate(attachments, 1):
        item = {'index': index, 'status': 'error'}
        if not isinstance(attachment, dict):
            item['error'] = '附件信息格式不正确。'
            results.append(item)
            continue
        item.update({k: attachment[k] for k in ('title', 'notice_attachment_id', 'url') if k in attachment})
        try:
            url = safe_url(attachment.get('url'), hosts)
            known_pdf = Path(urlsplit(url).path).suffix.lower() == '.pdf'
            if known_pdf:
                pdf_ordinal += 1
            for hop in range(4):
                response = transport.request('GET', url)
                if response.status not in (301, 302, 303, 307, 308):
                    break
                if hop == 3 or not response.headers.get('location'):
                    raise TransportError('附件跳转次数超过上限或缺少目标地址。')
                url = safe_url(urljoin(url, response.headers['location']), hosts)
            if response.status != 200:
                raise TransportError(f'附件 HTTP 状态为 {response.status}。')
            suffix = Path(urlsplit(url).path).suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,8}', suffix):
                suffix = '.bin'
            is_pdf = suffix == '.pdf' or 'application/pdf' in response.headers.get('content-type', '')
            if is_pdf:
                if not known_pdf:
                    pdf_ordinal += 1
                suffix = '.pdf'
                if not response.body.startswith(b'%PDF-'):
                    raise TransportError('附件响应不是有效 PDF 文件。')
            path = folder / f'attachment-{index}{suffix}'
            write_private(path, response.body)
            item.update(local_path=str(path), bytes=len(response.body), status='downloaded')
            if is_pdf:
                collection_path = Path(directory) / 'pdfs' / f'{folder.name}-{pdf_ordinal}.pdf'
                write_private(collection_path, response.body)
                item['collection_path'] = str(collection_path)
                item.update(extract_pdf(path))
                if item.get('text', '').strip():
                    text_path = path.with_suffix('.txt')
                    write_private(text_path, item['text'].encode('utf-8'))
                    item['text_path'] = str(text_path)
            else:
                item.update(text='', pages=None, status='not_pdf')
        except (ClientError, TransportError) as error:
            item['error'] = str(error)
            item['status'] = 'error'
        except (OSError, ValueError, TypeError):
            item['error'] = '附件保存或解析失败。'
            item['status'] = 'error'
        results.append(item)
    return results
