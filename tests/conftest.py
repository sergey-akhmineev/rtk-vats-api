import base64
import json
import time


def make_jwt(exp: int | None = None) -> str:
    if exp is None:
        exp = int(time.time()) + 3600
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"hdr.{payload}.sig"


AUTH_2FA_RESPONSE = {"two_factor": True, "hash": "2fa-session-abc"}
