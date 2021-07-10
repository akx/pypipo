from starlette.responses import Response
from starlette.types import Scope, Receive, Send

from pypipo.proxy import do_proxy_magic
from pypipo.utils import read_fd


async def app(scope: Scope, receive: Receive, send: Send):
    if scope["type"] in ("lifespan", "websocket"):
        return None

    if scope["method"] != "GET":
        return await Response("Method not allowed", 405)(scope, receive, send)
    user_response = await do_proxy_magic(scope, receive)
    return await user_response(scope, receive, send)
