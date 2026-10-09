"""User data locations and bounded, readable notice filenames."""
from pathlib import Path
import re
import unicodedata

from .client import ClientError, positive_int


def default_profile() -> Path:
    return Path.home() / '.config' / 'cannan-notice' / 'profile.json'


def default_directory() -> Path:
    return Path.home() / 'Documents' / 'Cannan Notices'


def safe_title(value: object, max_bytes: int = 180) -> str:
    if max_bytes < 1:
        raise ClientError('文件名的可用长度不足。')
    title = unicodedata.normalize('NFC', value) if isinstance(value, str) else ''
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', title).strip(' .')
    title = title or '未命名通告'
    return title.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore').rstrip(' .') or '_'


def notice_basename(detail: dict) -> str:
    identity = positive_int(detail.get('notice_id'), 'notice_id')
    prefix = f'notice-{identity}-'
    # Reserve room for the PDF ordinal, extension and rendering suffix.
    budget = min(180, 220 - len(prefix.encode('utf-8')))
    return prefix + safe_title(detail.get('title'), budget)


def notice_folder(detail: dict, directory: Path) -> Path:
    return Path(directory) / notice_basename(detail)
