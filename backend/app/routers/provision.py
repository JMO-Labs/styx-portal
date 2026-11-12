"""Provisioning webhook (ADR-0062): validate, check, de-duplicate and record approved
requests from Power Automate. Keycloak user creation and card binding are separate."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import jsonschema
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import ApprovedRequest
from app.security.provision_auth import require_provision_caller
from app.services.audit import audit_request

router = APIRouter()
_settings = Settings()
EXT = "urn:styx:scim:schemas:provisioning:1.0:Request"
_SCHEMA_REL = Path("docs/enterprise/schemas/scim-provisioning-v1.schema.json")


@lru_cache
def _validator() -> jsonschema.Draft202012Validator:
    here = Path(__file__).resolve()
    path = next(p for p in (here.parents[3] / _SCHEMA_REL, here.parents[2] / _SCHEMA_REL)
                if p.exists())
    defs = json.loads(path.read_text())["$defs"]
    return jsonschema.Draft202012Validator({"$ref": "#/$defs/user", "$defs": defs})


def _csv(raw: str) -> set[str]:
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _managers() -> dict[str, set[str]]:
    try:
        raw = json.loads(_settings.PROVISION_GROUP_MANAGERS or "{}")
    except ValueError:
        return {}
    return {g: {e.lower() for e in emails} for g, emails in raw.items()}


def _body_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
                          ).hexdigest()


def _result(row: ApprovedRequest) -> dict:
    return {"id": row.id, "externalId": row.external_id, "status": row.status}


async def _finish(session, request, action, status, code, *, key, approval=None,
                  approver=None, resource=None, replay: dict | None = None):
    """Audit (always) then respond; the audit row is committed before any error."""
    await audit_request(session, request, action, resource=resource, detail={
        "idempotency_key": key, "approval_id": approval, "approver": approver,
        "http_status": status, "styx_code": code})
    await session.commit()
    if replay is not None:
        return JSONResponse(replay, status_code=status, headers={"Idempotent-Replay": "true"})
    raise HTTPException(status_code=status, detail=code)


@router.post("/requests", status_code=201, dependencies=[Depends(require_provision_caller)])
async def create_request(request: Request,
                         idempotency_key: str | None = Header(default=None, max_length=128),
                         session: AsyncSession = Depends(get_session)):
    key = (idempotency_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="IDEMPOTENCY_KEY_MISSING")
    try:
        body = json.loads(await request.body())
        errors = list(_validator().iter_errors(body))
    except ValueError:
        body, errors = None, [True]
    if errors:  # never echo values: the body can hold PII
        await _finish(session, request, "provision.request.invalid", 422, "SCHEMA_INVALID",
                      key=key)
    ext = body[EXT]
    approval, approver, ext_id = ext["approvalId"], ext["approverEmail"], body["externalId"]
    ctx = {"key": key, "approval": approval, "approver": approver, "resource": ext_id}

    digest = _body_hash(body)
    prior = (await session.exec(select(ApprovedRequest).where(
        ApprovedRequest.idempotency_key == key))).first()
    if prior:
        if prior.body_hash != digest:
            await _finish(session, request, "provision.request.conflict", 409,
                          "IDEMPOTENCY_CONFLICT", **ctx)
        return await _finish(session, request, "provision.request.replay", 201, None,
                             replay=_result(prior), **ctx)

    admin = _csv(_settings.KEYCLOAK_ADMIN_GROUPS)
    if any(g.lower() in admin for g in ext["groups"]):
        await _finish(session, request, "provision.request.denied", 403,
                      "GROUP_NOT_ALLOWED", **ctx)
    managers = _managers()
    if not all(approver.lower() in managers.get(g, set()) for g in ext["groups"]):
        await _finish(session, request, "provision.request.denied", 403,
                      "APPROVER_UNKNOWN", **ctx)

    for col, val, code in ((ApprovedRequest.approval_id, approval, "APPROVAL_REUSED"),
                           (ApprovedRequest.external_id, ext_id, "USER_EXISTS")):
        if (await session.exec(select(ApprovedRequest.id).where(col == val))).first():
            await _finish(session, request, "provision.request.conflict", 409, code, **ctx)

    row = ApprovedRequest(
        idempotency_key=key, body_hash=digest, approval_id=approval, external_id=ext_id,
        approver_email=approver, groups=ext["groups"], card_type=ext["cardType"],
        person_type=ext["personType"], end_date=ext.get("endDate"),
        subject={"name": body["name"], "email": body["emails"][0]["value"],
                 "edipi": ext.get("edipi")})
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:  # concurrent duplicate won the race
        await session.rollback()
        await _finish(session, request, "provision.request.conflict", 409,
                      "APPROVAL_REUSED", **ctx)
    await audit_request(session, request, "provision.request.accepted", resource=ext_id,
                        detail={"idempotency_key": key, "approval_id": approval,
                                "approver": approver, "http_status": 201,
                                "request_id": row.id})
    await session.commit()
    return _result(row)
