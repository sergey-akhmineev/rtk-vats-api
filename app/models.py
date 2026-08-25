"""Pydantic-модели для удобных эндпоинтов.

Схемы ВАТС известны частично (по JS-бандлу ЛК), поэтому модели мягкие:
все поля опциональны, лишние поля пропускаются наверх как есть.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class SmsCode(BaseModel):
    code: str


class LoginRequest(BaseModel):
    """Вход через «Ростелеком Паспорт». Пустые поля берутся из .env."""

    username: Optional[str] = None
    password: Optional[str] = None
    by_code: bool = False  # войти по одноразовому коду, без пароля


class TokenImport(BaseModel):
    token: str
    refresh_token: str = ""
    fingerprint: str = ""


class ContactNumber(BaseModel):
    model_config = ConfigDict(extra="allow")

    number: str
    contactType: Optional[str] = None  # mobile / work / home / fax ...


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    groupId: Optional[int] = None
    numbers: Optional[list[ContactNumber]] = None


class ContactUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    groupId: Optional[int] = None
    numbers: Optional[list[ContactNumber]] = None


class GroupIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str


class GroupUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None


class UserIn(BaseModel):
    """Создание/редактирование абонента домена — поля уточнятся на живом API."""

    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    displayName: Optional[str] = None


class CallsQuery(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class GenericBody(BaseModel):
    """Произвольное тело для passthrough-операций."""

    model_config = ConfigDict(extra="allow")

    data: Optional[dict[str, Any]] = None
