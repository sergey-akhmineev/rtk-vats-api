"""Общие хелперы роутеров: обработка ошибок и passthrough ответов ВАТС."""

from typing import Any

import httpx
from fastapi import HTTPException, Response

from ..browser_login import BrowserLoginError, BrowserLoginUnavailable
from ..pbx_client import PBXAuthRequired, PBXError

_HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length"}


def json_or_body(resp: httpx.Response) -> Any:
    """JSON, если он есть; иначе сырой текст."""
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "body": resp.text[:2000]}


def passthrough(resp: httpx.Response) -> Response:
    """Ответ ВАТС как есть (для бинарных: записи разговоров, факсы, выгрузки)."""
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP}
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=headers,
        media_type=resp.headers.get("content-type"),
    )


def map_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, BrowserLoginUnavailable):
        return HTTPException(status_code=501, detail=str(exc))
    if isinstance(exc, BrowserLoginError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, PBXAuthRequired):
        return HTTPException(status_code=503, detail=exc.detail)
    if isinstance(exc, PBXError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    if isinstance(exc, httpx.HTTPError):
        return HTTPException(status_code=502, detail=f"ВАТС недоступна: {exc}")
    return HTTPException(status_code=500, detail=str(exc))
