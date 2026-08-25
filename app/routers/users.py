"""Абоненты и группы вызовов домена: /users, /groups.

Маппинг на ВАТС:
  GET    /domain/users, POST /domain/users, PUT/DELETE /domain/users/{id}
  GET    /domain/groups, POST /domain/groups, GET/PUT/DELETE /domain/groups/{id}
"""

from fastapi import APIRouter, Depends

from ..deps import get_pbx_client
from ..models import UserIn
from ..pbx_client import PBXClient
from ._common import json_or_body, map_errors

router = APIRouter(tags=["users"])


@router.get("/users")
async def list_users(client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("GET", "/domain/users"))
    except Exception as exc:
        raise map_errors(exc)


@router.post("/users", status_code=201)
async def create_user(body: UserIn, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("POST", "/domain/users", json_body=body.model_dump(exclude_none=True)))
    except Exception as exc:
        raise map_errors(exc)


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: UserIn, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(
            await client.request("PUT", f"/domain/users/{user_id}", json_body=body.model_dump(exclude_none=True))
        )
    except Exception as exc:
        raise map_errors(exc)


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("DELETE", f"/domain/users/{user_id}"))
    except Exception as exc:
        raise map_errors(exc)


@router.get("/groups")
async def list_groups(client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("GET", "/domain/groups"))
    except Exception as exc:
        raise map_errors(exc)


@router.get("/groups/{group_id}")
async def get_group(group_id: int, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("GET", f"/domain/groups/{group_id}"))
    except Exception as exc:
        raise map_errors(exc)


@router.post("/groups", status_code=201)
async def create_group(body: UserIn, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(
            await client.request("POST", "/domain/groups", json_body=body.model_dump(exclude_none=True))
        )
    except Exception as exc:
        raise map_errors(exc)


@router.put("/groups/{group_id}")
async def update_group(group_id: int, body: UserIn, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(
            await client.request("PUT", f"/domain/groups/{group_id}", json_body=body.model_dump(exclude_none=True))
        )
    except Exception as exc:
        raise map_errors(exc)


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int, client: PBXClient = Depends(get_pbx_client)):
    try:
        return json_or_body(await client.request("DELETE", f"/domain/groups/{group_id}"))
    except Exception as exc:
        raise map_errors(exc)
