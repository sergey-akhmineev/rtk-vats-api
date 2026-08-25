"""Домен: номера, баланс, настройки.

Маппинг на ВАТС:
  GET /domain/numbers            -> номера домена и правила маршрутизации
  GET /domain/payments/balance   -> баланс лицевого счёта
  GET /domain/settings           -> настройки домена
"""

from fastapi import APIRouter, Depends

from ..deps import get_pbx_client
from ..pbx_client import PBXClient
from ._common import json_or_body, map_errors

router = APIRouter(tags=["domain"])


@router.get("/numbers")
async def list_numbers(client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("GET", "/domain/numbers"))
    except Exception as exc:
        raise map_errors(exc)


@router.get("/balance")
async def balance(client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("GET", "/domain/payments/balance"))
    except Exception as exc:
        raise map_errors(exc)


@router.get("/settings")
async def domain_settings(client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("GET", "/domain/settings"))
    except Exception as exc:
        raise map_errors(exc)
