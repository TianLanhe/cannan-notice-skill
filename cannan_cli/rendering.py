"""Offline PDF page rendering for visual attachment reading."""
import io
from contextlib import closing
import math
from pathlib import Path
import re

from .attachments import write_private
from .client import ClientError
from .paths import safe_title


def select_pages(raw: str | None, total: int) -> list[int]:
    if not isinstance(total, int) or total < 1:
        raise ClientError('PDF 没有可读取的页面。')
    if raw is None:
        return list(range(1, total + 1))
    selected = set()
    for part in raw.split(','):
        match = re.fullmatch(r'\s*([0-9]+)(?:-([0-9]+))?\s*', part)
        if not match:
            raise ClientError('--pages 应为从 1 开始的页码或范围，例如 1,3-5。')
        start = int(match[1])
        end = int(match[2]) if match[2] else start
        if not 1 <= start <= end <= total:
            raise ClientError('所选页码超出 PDF 范围或区间倒置。')
        selected.update(range(start, end + 1))
    return sorted(selected)


def render_pdf(path: Path, directory: Path | None = None, pages: str | None = None) -> dict:
    path = Path(path).expanduser().resolve()
    directory = Path(directory).expanduser().resolve() if directory is not None else path.parent / (safe_title(path.stem, 220) + '-pages')
    result = dict(source=str(path), total_pages=None, rendered_pages=[], images=[], errors=[], complete=False)
    try:
        import pypdfium2 as pdfium
        from PIL import Image  # Dependency check before opening the document.
    except ImportError:
        result['errors'].append({'error': 'PDF 渲染依赖缺失，请通过 scripts/cannan 准备环境。'})
        return result
    try:
        with pdfium.PdfDocument(path) as document:
            result['total_pages'] = len(document)
            selected = select_pages(pages, len(document))
            for number in selected:
                try:
                    with closing(document[number - 1]) as page:
                        width, height = page.get_size()
                        if not all(math.isfinite(x) and x > 0 for x in (width, height)):
                            raise ValueError('invalid page dimensions')
                        scale = min(2.0, 10000 / width, 10000 / height, math.sqrt(20_000_000 / (width * height)))
                        while math.ceil(width * scale) * math.ceil(height * scale) > 20_000_000:
                            scale *= 0.999
                        with closing(page.render(scale=scale, draw_annots=True)) as bitmap:
                            image = bitmap.to_pil()
                            try:
                                output = io.BytesIO()
                                image.save(output, format='PNG')
                            finally:
                                image.close()
                            target = directory / f'page-{number:04d}.png'
                            write_private(target, output.getvalue())
                    result['rendered_pages'].append(number)
                    result['images'].append({'page': number, 'local_path': str(target), 'scale': scale})
                except (OSError, ValueError, pdfium.PdfiumError, RuntimeError, OverflowError):
                    result['errors'].append({'page': number, 'error': '该页渲染或保存失败；已生成的页面保留。'})
            result['complete'] = not result['errors']
    except ClientError:
        raise
    except (OSError, ValueError, pdfium.PdfiumError, RuntimeError):
        result['errors'].append({'error': '无法读取 PDF，文件可能不存在、损坏或需要解密。'})
    return result
