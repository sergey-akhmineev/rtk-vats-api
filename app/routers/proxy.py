"""Прозрачный прокси на любой эндпоинт /webapi/* ВАТС.

Примеры:
  GET  /proxy/domain/contacts/users
  GET  /proxy/domain/call_history?date_from=2026-08-01
  POST /proxy/domain/contacts/group  {"name": "Врачи"}
"""

from fastapi import APIRouter, Depends, Request

from ..deps import get_pbx_client
from ..pbx_client import PBXClient
from ._common import map_errors, passthrough

router = APIRouter(prefix="/proxy", tags=["proxy"])

_SKIP_REQ_HEADERS = {"host", "authorization", "x-api-key", "content-length", "connection"}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request, client: PBXClient = Depends(get_pbx_client)):
    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _SKIP_REQ_HEADERS and not k.lower().startswith("x-")
    }
    try:
        resp = await client.request(
            request.method,
            f"/{path}",
            params=dict(request.query_params),
            content=body if body else None,
            headers=headers,
        )
    except Exception as exc:
        raise map_errors(exc)
    return passthrough(resp)
