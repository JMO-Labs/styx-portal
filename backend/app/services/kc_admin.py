"""Minimal Keycloak admin client: disable/delete user, remove from group.

Least privilege (ADR-0051): no role-mapping operations are exposed.
"""
import logging
import time
from urllib.parse import quote
from collections.abc import Callable

import httpx

from app.config import Settings

logger = logging.getLogger("styx-portal")

_EXPIRY_SKEW_S = 10


def _seg(value: str) -> str:
    return quote(value, safe="")


class KeycloakAdminError(Exception):
    """Keycloak returned a non-success response."""


class KeycloakAdminClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._base = settings.KC_ADMIN_URL.rstrip("/")
        self._realm = settings.KC_ADMIN_REALM
        self._cid = settings.KC_ADMIN_CLIENT_ID
        self._secret = settings.KC_ADMIN_CLIENT_SECRET
        self._transport = transport
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    @property
    def enabled(self) -> bool:
        return all((self._base, self._realm, self._cid, self._secret))

    async def _get_token(self, http: httpx.AsyncClient) -> str:
        if self._token and self._clock() < self._expires_at:
            return self._token
        resp = await http.post(
            f"{self._base}/realms/{self._realm}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._cid,
                "client_secret": self._secret,
            },
        )
        if resp.status_code != 200:
            raise KeycloakAdminError(f"token request failed: {resp.status_code}")
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = self._clock() + int(data.get("expires_in", 60)) - _EXPIRY_SKEW_S
        return self._token

    async def _request(self, op: str, method: str, path: str, json: dict | None = None) -> None:
        if not self.enabled:
            logger.info("kc_admin.disabled op=%s", op)
            return
        async with httpx.AsyncClient(transport=self._transport, timeout=10) as http:
            token = await self._get_token(http)
            resp = await http.request(
                method,
                f"{self._base}/admin/realms/{self._realm}{path}",
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code == 404:  # already gone: idempotent
            return
        if not 200 <= resp.status_code < 300:
            raise KeycloakAdminError(f"{op} failed: {resp.status_code}")

    async def disable_user(self, kc_user_id: str) -> None:
        await self._request("disable_user", "PUT", f"/users/{_seg(kc_user_id)}", {"enabled": False})

    async def delete_user(self, kc_user_id: str) -> None:
        await self._request("delete_user", "DELETE", f"/users/{_seg(kc_user_id)}")

    async def remove_from_group(self, kc_user_id: str, group_id: str) -> None:
        await self._request(
            "remove_from_group", "DELETE", f"/users/{_seg(kc_user_id)}/groups/{_seg(group_id)}"
        )


_instance: KeycloakAdminClient | None = None


def _client() -> KeycloakAdminClient:
    global _instance
    if _instance is None:
        _instance = KeycloakAdminClient(Settings())
    return _instance


def reset_client() -> None:
    global _instance
    _instance = None


async def disable_user(kc_user_id: str) -> None:
    await _client().disable_user(kc_user_id)


async def delete_user(kc_user_id: str) -> None:
    await _client().delete_user(kc_user_id)


async def remove_from_group(kc_user_id: str, group_id: str) -> None:
    await _client().remove_from_group(kc_user_id, group_id)
