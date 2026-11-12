"""Provision approved requests into Keycloak (ADR-0051/0052, styx-portal#121).

Idempotent: progress (kc_user_id, username, applied groups) is kept in
`request.subject`, so a retry after a failure resumes instead of duplicating.
"""
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import ApprovedRequest
from app.services import kc_admin
from app.services.audit import audit
from app.services.kc_admin import KeycloakAdminError, make_username
from app.services.posix_uid import allocate_uid

OPS = ("create", "update", "disable")


def _save(row: ApprovedRequest, **kv) -> None:
    row.subject = {**row.subject, **kv}
    flag_modified(row, "subject")


async def _sync_groups(row: ApprovedRequest, kc_id: str) -> None:
    have = list(row.subject.get("kc_groups", []))
    want = list(row.groups)
    for g in [g for g in have if g not in want]:
        await kc_admin.remove_from_group(kc_id, g)
        have.remove(g)
        _save(row, kc_groups=have)
    for g in [g for g in want if g not in have]:
        await kc_admin.add_to_group(kc_id, g)
        have.append(g)
        _save(row, kc_groups=have)


async def _create(session: AsyncSession, row: ApprovedRequest) -> None:
    s = row.subject
    if not s.get("kc_user_id"):
        name = s["name"]
        username = s.get("username") or make_username(
            name["givenName"], name["familyName"], set())
        kc_id = await kc_admin.create_user(
            username, s["email"], name["givenName"], name["familyName"])
        _save(row, kc_user_id=kc_id, username=username)
    uid = await allocate_uid(session, row.external_id)
    await kc_admin.set_attributes(row.subject["kc_user_id"], {"posix_uid": [str(uid)]})
    await _sync_groups(row, row.subject["kc_user_id"])


async def _update(row: ApprovedRequest) -> None:
    s, kc_id = row.subject, row.subject["kc_user_id"]
    await kc_admin.update_user(kc_id, {
        "email": s["email"], "firstName": s["name"]["givenName"],
        "lastName": s["name"]["familyName"]})
    await _sync_groups(row, kc_id)


async def provision(session: AsyncSession, request: ApprovedRequest,
                    op: str = "create") -> ApprovedRequest:
    """Apply `op` to Keycloak. Failures set status `failed` (audited); retry is safe."""
    if op not in OPS:
        raise ValueError(f"unknown provisioning op: {op}")
    prev = request.status if request.status != "failed" else request.subject.get(
        "status_before", "pending_binding")
    try:
        if op == "create":
            await _create(session, request)
        elif op == "update":
            await _update(request)
        else:
            await kc_admin.disable_user(request.subject["kc_user_id"])
        request.status = "disabled" if op == "disable" else prev
    except (KeycloakAdminError, KeyError) as exc:
        _save(request, status_before=prev)
        request.status = "failed"
        await audit(session, "provision.failed", resource=request.external_id,
                    detail={"op": op, "error": type(exc).__name__, "request_id": request.id})
    else:
        await audit(session, f"provision.{op}", resource=request.external_id,
                    detail={"request_id": request.id})
    session.add(request)
    await session.commit()
    return request
