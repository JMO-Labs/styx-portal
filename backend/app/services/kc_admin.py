"""Minimal Keycloak admin client: provisioning and offboarding calls.

Least privilege (ADR-0051): no role-mapping operations are exposed.
"""
import logging
import re
import time
import unicodedata
from urllib.parse import quote
from collections.abc import Callable

import httpx

from app.config import Settings

logger = logging.getLogger("styx-portal")

_EXPIRY_SKEW_S = 10


def _seg(value: str) -> str:
    return quote(value, safe="")


def make_username(first: str, last: str, taken: set[str]) -> str:
    """ADR-0016: `first.last`; append a digit (1, 2, ...) on collision."""

    def clean(v: str) -> str:
        v = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]", "", v.lower())

    base = f"{clean(first)}.{clean(last)}"
    name, n = base, 0
    while name in taken:
        n += 1
        name = f"{base}{n}"
    return name


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
        self._admin_groups = {
            g.strip() for g in settings.KEYCLOAK_ADMIN_GROUPS.split(",") if g.strip()
        }
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

    async def _request(self, op: str, method: str, path: str, json: dict | None = None,
        allow_404: bool = False,
    ) -> httpx.Response | None:
        if not self.enabled:
            logger.info("kc_admin.disabled op=%s", op)
            return None
        async with httpx.AsyncClient(transport=self._transport, timeout=10) as http:
            token = await self._get_token(http)
            resp = await http.request(
                method,
                f"{self._base}/admin/realms/{self._realm}{path}",
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code == 404 and allow_404:  # already gone: idempotent
            return resp
        if not 200 <= resp.status_code < 300:
            raise KeycloakAdminError(f"{op} failed: {resp.status_code}")
        return resp

    async def create_user(self, username: str, email: str, first_name: str, last_name: str) -> str:
        """Create an enabled user; returns the new Keycloak user id ('' when disabled)."""
        resp = await self._request(
            "create_user", "POST", "/users",
            {"username": username, "email": email, "firstName": first_name,
             "lastName": last_name, "enabled": True},
        )
        if resp is None:
            return ""
        return resp.headers.get("Location", "").rstrip("/").rsplit("/", 1)[-1]

    async def update_user(self, kc_user_id: str, fields: dict) -> None:
        await self._request("update_user", "PUT", f"/users/{_seg(kc_user_id)}", fields)

    async def set_attributes(self, kc_user_id: str, attributes: dict[str, list[str]]) -> None:
        """PUT {attributes}. Keycloak replaces the whole attribute map: pass the full map."""
        await self._request(
            "set_attributes", "PUT", f"/users/{_seg(kc_user_id)}", {"attributes": attributes}
        )

    async def add_to_group(self, kc_user_id: str, group_id: str) -> None:
        if group_id in self._admin_groups:
            raise KeycloakAdminError("add_to_group refused: admin group")
        await self._request(
            "add_to_group", "PUT", f"/users/{_seg(kc_user_id)}/groups/{_seg(group_id)}"
        )

    async def disable_user(self, kc_user_id: str) -> None:
        await self._request(
            "disable_user", "PUT", f"/users/{_seg(kc_user_id)}", {"enabled": False},
            allow_404=True,
        )

    async def delete_user(self, kc_user_id: str) -> None:
        await self._request(
            "delete_user", "DELETE", f"/users/{_seg(kc_user_id)}", allow_404=True
        )

    async def remove_from_group(self, kc_user_id: str, group_id: str) -> None:
        await self._request(
            "remove_from_group", "DELETE", f"/users/{_seg(kc_user_id)}/groups/{_seg(group_id)}",
            allow_404=True,
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


async def create_user(username: str, email: str, first_name: str, last_name: str) -> str:
    return await _client().create_user(username, email, first_name, last_name)


async def update_user(kc_user_id: str, fields: dict) -> None:
    await _client().update_user(kc_user_id, fields)


async def set_attributes(kc_user_id: str, attributes: dict[str, list[str]]) -> None:
    await _client().set_attributes(kc_user_id, attributes)


async def add_to_group(kc_user_id: str, group_id: str) -> None:
    await _client().add_to_group(kc_user_id, group_id)
