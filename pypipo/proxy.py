import base64
import gzip
import pickle
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from asgiproxy.config import ProxyConfig
from asgiproxy.context import ProxyContext
from asgiproxy.proxies.http import get_proxy_response
from starlette.responses import Response, StreamingResponse
from starlette.types import Scope

from pypipo.utils import read_fd


class PypiProxy(ProxyConfig):
    def get_upstream_url(self, scope: Scope) -> str:
        return urljoin(scope["host"], scope["path"])

    def process_client_headers(self, *, scope: Scope, headers):
        headers = headers.mutablecopy()  # type: ignore
        headers["host"] = urlparse(scope["host"]).hostname
        return super().process_client_headers(scope=scope, headers=headers)  # type: ignore


pctx = ProxyContext(PypiProxy())


async def do_proxy_magic(scope, receive):
    our_host = dict(scope["headers"])[b"host"].decode()
    up_scope = scope.copy()
    if up_scope["path"].startswith("/~/"):
        encoded_host, _, path = up_scope["path"][3:].partition("/")
        up_scope["host"] = base64.urlsafe_b64decode(encoded_host).decode()
        up_scope["path"] = path
    else:
        up_scope["host"] = "https://pypi.org/"

    hostname = urlparse(up_scope["host"]).hostname

    if hostname not in ("pypi.org", "files.pythonhosted.org"):
        return Response(f"Refusing host: {hostname}", 401)

    cache_basename = Path("./cache") / hostname / up_scope["path"].lstrip("/")
    cache_meta_path = cache_basename.with_name(cache_basename.name + ".meta.pickle")
    cache_data_path = cache_basename
    if cache_meta_path.is_file() and cache_data_path.is_file():
        meta = pickle.loads(cache_meta_path.read_bytes())
        content_reader = read_fd(cache_data_path.open("rb"))
    else:
        proxy_response = await get_proxy_response(
            context=pctx, scope=up_scope, receive=receive
        )
        headers = proxy_response.headers.copy()
        # TODO: this probably shouldn't buffer very large responses into memory
        content = await proxy_response.read()
        if headers["content-type"].startswith("text/html"):
            if headers.get("content-encoding") == "gzip":
                content = gzip.decompress(content)
                del headers["content-encoding"]

            content = re.sub(
                'href="(https://[^/]+)',
                lambda m: fr'href="http://{our_host}/~/'
                + base64.urlsafe_b64encode(m.group(1).encode()).decode(),
                content.decode(),
            ).encode()
            headers.popall("content-length", None)
        cache_meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "status_code": proxy_response.status,
            "headers": headers,
        }
        cache_meta_path.write_bytes(pickle.dumps(meta))
        cache_data_path.write_bytes(content)
        del content
        content_reader = read_fd(cache_data_path.open("rb"))
    return StreamingResponse(
        content_reader,
        **meta,
    )
