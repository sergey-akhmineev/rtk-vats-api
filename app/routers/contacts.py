"""Контакты домена: /contacts, /contacts/groups, /contacts/users.

Маппинг на ВАТС:
  GET    /domain/contacts                    -> группы с контактами
  POST   /domain/contacts                    -> создать контакт
  PUT    /domain/contacts/{id}               -> изменить контакт
  DELETE /domain/contacts/{id}               -> удалить контакт
  POST   /domain/contacts/group              -> создать группу
  PUT    /domain/contacts/group/{id}         -> переименовать группу
  DELETE /domain/contacts/group/{id}         -> удалить группу
  GET    /domain/contacts/users              -> абоненты домена (внутренние)
"""

from fastapi import APIRouter, Depends

from ..deps import get_pbx_client
from ..models import ContactIn, ContactUpdate, GroupIn, GroupUpdate
from ..pbx_client import PBXClient
from ._common import json_or_body, map_errors

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("")
async def list_contacts(client: PBXClient = Depends(get_pbx_client)):
    """Группы контактов домена вместе с контактами."""
    try:
        return json_or_body(await client.request("GET", "/domain/contacts"))
    except Exception as exc:
        raise map_errors(exc)


@router.post("", status_code=201)
async def create_contact(body: ContactIn, client: PBXClient = Depends(get_pbx_client)):
    try:
        payload = body.model_dump(exclude_none=True)
        return json_or_body(await client.request("POST", "/domain/contacts", json_body=payload))
    except Exception as exc:
        raise map_errors(exc)


@router.put("/{contact_id}")
async def update_contact(contact_id: int, body: ContactUpdate, client: PBXClient = Depends(get_pbx_client)):
    try:
        payload = body.model_dump(exclude_none=True)
        return json_or_body(await client.request("PUT", f"/domain/contacts/{contact_id}", json_body=payload))
    except Exception as exc:
        raise map_errors(exc)


@router.delete("/{contact_id}")
async def delete_contact(contact_id: int, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("DELETE", f"/domain/contacts/{contact_id}"))
    except Exception as exc:
        raise map_errors(exc)


@router.post("/groups", status_code=201)
async def create_group(body: GroupIn, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(
            await client.request("POST", "/domain/contacts/group", json_body=body.model_dump(exclude_none=True))
        )
    except Exception as exc:
        raise map_errors(exc)


@router.put("/groups/{group_id}")
async def update_group(group_id: int, body: GroupUpdate, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(
            await client.request(
                "PUT", f"/domain/contacts/group/{group_id}", json_body=body.model_dump(exclude_none=True)
            )
        )
    except Exception as exc:
        raise map_errors(exc)


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("DELETE", f"/domain/contacts/group/{group_id}"))
    except Exception as exc:
        raise map_errors(exc)


@router.get("/users")
async def domain_users(client: PBXClient = Depends(get_pbx_client)):
    """Абоненты домена (внутренние пользователи с номерами и PIN)."""
    try:
        return json_or_body(await client.request("GET", "/domain/contacts/users"))
    except Exception as exc:
        raise map_errors(exc)
