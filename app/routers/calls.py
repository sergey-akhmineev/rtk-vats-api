"""История звонков: /calls.

Маппинг на ВАТС:
  GET /domain/call_history                      -> список звонков (query-параметры пробрасываются)
  GET /domain/call_history/stat                 -> статистика
  GET /domain/call_history/{callId}/protocol    -> поэтапный протокол звонка
  GET /domain/call_history/{callId}/record      -> запись разговора (бинарный поток)
"""

from fastapi import APIRouter, Depends, Request

from ..deps import get_pbx_client
from ..pbx_client import PBXClient
from ._common import json_or_body, map_errors, passthrough

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get("")
async def call_history(request: Request, client: PBXClient = Depends(get_pbx_client)):
    """История звонков. Query-параметры ВАТС (date_from/date_to/…) пробрасываются как есть."""
    try:
        return json_or_body(await client.request("GET", "/domain/call_history", params=dict(request.query_params)))
    except Exception as exc:
        raise map_errors(exc)


@router.get("/stat")
async def call_stat(request: Request, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(
            await client.request("GET", "/domain/call_history/stat", params=dict(request.query_params))
        )
    except Exception as exc:
        raise map_errors(exc)


@router.get("/{call_id}/protocol")
async def call_protocol(call_id: str, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("GET", f"/domain/call_history/{call_id}/protocol"))
    except Exception as exc:
        raise map_errors(exc)


@router.get("/{call_id}/record")
async def call_record(call_id: str, client: PBXClient = Depends(get_pbx_client)):
    """Скачивание записи разговора (audio/*)."""
    try:
        return passthrough(await client.request("GET", f"/domain/call_history/{call_id}/record"))
    except Exception as exc:
        raise map_errors(exc)
