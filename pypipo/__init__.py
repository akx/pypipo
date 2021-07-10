import base64
import gzip
import pickle
import re
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

from asgiproxy.config import ProxyConfig
from asgiproxy.context import ProxyContext
from asgiproxy.proxies.http import get_proxy_response
from starlette.responses import Response
from starlette.types import Scope, Receive, Send


class PypiProxy(ProxyConfig):
    def get_upstream_url(self, scope: Scope) -> str:
        return urljoin(scope["host"], scope["path"])

    def process_client_headers(self, *, scope: Scope, headers):
        headers = headers.mutablecopy()  # type: ignore
        headers["host"] = urlparse(scope["host"]).hostname
        return super().process_client_headers(scope=scope, headers=headers)  # type: ignore


pctx = ProxyContext(PypiProxy())


async def app(scope: Scope, receive: Receive, send: Send):
    if scope["type"] in ("lifespan", "websocket"):
        return None

    if scope["method"] != "GET":
        return await Response("Method not allowed", 405)(scope, receive, send)
    user_response = await do_proxy_magic(scope, receive)
    return await user_response(scope, receive, send)


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

    cache_file_path = (
        Path("./cache") / hostname / up_scope["path"].lstrip("/")
    ).with_suffix(".pickle")
    if cache_file_path.is_file():
        user_response = pickle.loads(cache_file_path.read_bytes())
    else:
        proxy_response = await get_proxy_response(
            context=pctx, scope=up_scope, receive=receive
        )
        headers = proxy_response.headers.copy()
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
        user_response = Response(
            content=content,
            status_code=proxy_response.status,
            headers=headers,  # type: ignore
        )
        cache_file_path.parent.mkdir(parents=True, exist_ok=True)
        cache_file_path.write_bytes(
            pickle.dumps(user_response, protocol=pickle.HIGHEST_PROTOCOL)
        )
    return user_response
