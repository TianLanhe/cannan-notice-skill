"""HTTPS transport. Secrets stay out of process arguments and error messages."""
from dataclasses import dataclass
import ipaddress
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

API_HOST = 'apps.cannan.edu.hk'


class TransportError(RuntimeError):
    pass


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def safe_url(url: str, allowed_hosts: set[str]) -> str:
    try:
        u = urlsplit(url)
        if (u.scheme != 'https' or u.hostname not in allowed_hosts or u.username is not None
                or u.password is not None or u.port not in (None, 443)):
            raise ValueError()
        return urlunsplit(('https', u.netloc, quote(u.path, safe='/%:@-._~'),
                           quote(u.query, safe='%&=+/:?@-._~'), ''))
    except (ValueError, TypeError):
        raise TransportError('仅允许配置范围内的 HTTPS 地址（443），禁止 URL 中含用户凭据。') from None


class CurlTransport:
    def __init__(self, proxy=None, ca_bundle=None, resolve=None, timeout=25,
                 max_bytes=20971520, allowed_hosts=None):
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise TransportError('请求超时必须是正数。')
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise TransportError('下载大小上限必须是正整数。')
        self.timeout, self.max_bytes = timeout, max_bytes
        self.allowed_hosts = set(allowed_hosts or {API_HOST})
        self.proxy, self.ca_bundle = proxy, ca_bundle
        self.resolve = resolve or {}
        if not isinstance(self.resolve, dict):
            raise TransportError('resolve 配置必须是主机到 IP 的映射。')
        try:
            for host, address in self.resolve.items():
                if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9.-]+', host):
                    raise ValueError()
                ipaddress.ip_address(address)
            if proxy:
                p = urlsplit(proxy)
                if p.scheme not in ('http', 'https', 'socks5', 'socks5h') or not p.hostname or p.username is not None:
                    raise ValueError()
                _ = p.port
        except (ValueError, TypeError):
            raise TransportError('代理或临时解析地址格式不正确。') from None

    def request(self, method: str, url: str, params: dict | None = None) -> HttpResponse:
        if method not in ('GET', 'POST'):
            raise TransportError('不支持此请求方法。')
        if params:
            u = urlsplit(url)
            query = '&'.join(filter(None, (u.query, urlencode(params))))
            url = urlunsplit((u.scheme, u.netloc, u.path, query, ''))
        url = safe_url(url, self.allowed_hosts)
        curl = shutil.which('curl')
        if not curl:
            raise TransportError('未找到 curl，请先安装 curl。')
        with tempfile.TemporaryDirectory(prefix='cannan-http-') as directory:
            body, headers = Path(directory) / 'body', Path(directory) / 'headers'
            for file in (body, headers):
                fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            args = [curl, '--disable', '--silent', '--show-error', '--globoff', '--compressed',
                    '--config', '-', '--request', method, '--output', str(body),
                    '--dump-header', str(headers), '--write-out', '%{http_code}',
                    '--max-time', str(self.timeout), '--connect-timeout', str(min(self.timeout, 10)),
                    '--max-filesize', str(self.max_bytes), '--proto', '=https', '--proto-redir', '=https']
            if self.proxy:
                args += ['--proxy', self.proxy, '--noproxy', '']
            else:
                args += ['--noproxy', '*']
            if self.ca_bundle:
                args += ['--cacert', str(self.ca_bundle)]
            host = urlsplit(url).hostname
            if host in self.resolve:
                ip = str(self.resolve[host])
                if ':' in ip:
                    ip = '[' + ip + ']'
                args += ['--resolve', f'{host}:443:{ip}']
            config = 'url = "' + url.replace('\\', '\\\\').replace('"', '\\"') + '"\n'
            try:
                result = subprocess.run(args, input=config, text=True, capture_output=True,
                                        timeout=self.timeout + 5, check=False)
            except (OSError, subprocess.TimeoutExpired):
                raise TransportError('HTTPS 请求执行失败或超时。') from None
            if result.returncode:
                hint = ' 检查 DNS、CA 或显式代理配置；证书校验仍保持开启。' if result.returncode == 60 else ''
                raise TransportError(f'HTTPS 请求失败（curl 退出码 {result.returncode}）。{hint}')
            try:
                status = int(result.stdout.strip())
                if not 100 <= status <= 599:
                    raise ValueError()
            except ValueError:
                raise TransportError('无法识别 HTTP 响应状态。') from None
            if body.stat().st_size > self.max_bytes:
                raise TransportError('响应超过配置的大小上限。')
            parsed = {}
            for line in headers.read_text(errors='replace').splitlines():
                if line.startswith('HTTP/'):
                    parsed = {}
                elif ':' in line:
                    name, value = line.split(':', 1)
                    parsed[name.lower().strip()] = value.strip()
            return HttpResponse(status, parsed, body.read_bytes())
