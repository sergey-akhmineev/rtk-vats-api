"""Персистентное хранение сессии ВАТС: JWT, refresh-токен, two_factor_session.

Файл data/session.json, атомарная запись (tmp + rename), права 600.
"""

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def _jwt_exp(token: str) -> Optional[int]:
    """Достаёт exp из JWT без проверки подписи."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


class SessionStore:
    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / "session.json"
        self._state: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            self._state = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._state = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # --- токены ---

    def save_tokens(self, token: str, refresh_token: str, fingerprint: str = "") -> None:
        self._state["token"] = token
        self._state["refresh_token"] = refresh_token
        if fingerprint:
            self._state["fingerprint"] = fingerprint
        self._state["expires_at"] = _jwt_exp(token)
        self._state.pop("two_factor_session", None)
        self._save()

    @property
    def token(self) -> Optional[str]:
        return self._state.get("token")

    @property
    def refresh_token(self) -> Optional[str]:
        return self._state.get("refresh_token")

    @property
    def fingerprint(self) -> Optional[str]:
        return self._state.get("fingerprint")

    @property
    def expires_at(self) -> Optional[int]:
        return self._state.get("expires_at")

    def seconds_left(self) -> Optional[int]:
        exp = self.expires_at
        if exp is None:
            return None
        return int(exp - time.time())

    def is_authenticated(self, margin: int = 30) -> bool:
        left = self.seconds_left()
        return left is not None and left > margin

    # --- 2FA ---

    def save_two_factor_session(self, value: str) -> None:
        self._state["two_factor_session"] = value
        self._save()

    @property
    def two_factor_session(self) -> Optional[str]:
        return self._state.get("two_factor_session")

    def clear(self) -> None:
        self._state = {}
        self._save()
