"""Short-lived unlock tokens for the gateway (ADR-0039, R02).

Per-instance key = HKDF-SHA256(JWT_SECRET, info="styx-unlock:<instance_id>").
Token = "<exp>.<hex HMAC-SHA256(key, "<instance_id>:<exp>")>", valid 60 s.
"""
import hashlib
import hmac
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Settings

TTL_S = 60


def unlock_key(instance_id: str) -> bytes:
    secret = Settings().jwt_secret_or_raise().encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=f"styx-unlock:{instance_id}".encode()).derive(secret)


def mint_token(instance_id: str, now: int | None = None) -> str:
    exp = int(time.time() if now is None else now) + TTL_S
    mac = hmac.new(unlock_key(instance_id), f"{instance_id}:{exp}".encode(),
                   hashlib.sha256).hexdigest()
    return f"{exp}.{mac}"
