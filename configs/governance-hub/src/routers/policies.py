"""OPA policy editor router.

Admin-only CRUD for .rego files under /opa-policies, with OPA-as-linter
on save and a dry-run evaluator that lets admins paste sample input JSON
and see the {allow, deny_reasons, obligations} decision before publishing.

Endpoints
---------
GET    /api/v1/policies            list installed .rego files
GET    /api/v1/policies/{path}     read a policy
PUT    /api/v1/policies/{path}     create or update (validates via OPA)
DELETE /api/v1/policies/{path}     delete
POST   /api/v1/policies/eval       dry-run eval against current bundle
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..services import opa_admin

logger = logging.getLogger("insidellm.policies_router")

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


def _require_admin(request: Request) -> None:
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Policy editing requires admin role")


def _caller(request: Request) -> str:
    return getattr(request.state, "user_id", "") or "unknown"


@router.get("")
async def list_policies(request: Request) -> dict:
    _require_admin(request)
    return {"policies": opa_admin.list_policies()}


@router.get("/{path:path}")
async def get_policy(path: str, request: Request) -> dict:
    _require_admin(request)
    try:
        return {"path": path, "content": opa_admin.read_policy(path)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Policy not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{path:path}")
async def save_policy(
    path: str,
    request: Request,
    payload: dict = Body(...),
) -> dict:
    _require_admin(request)
    rego = payload.get("content", "")
    if not rego.strip():
        raise HTTPException(status_code=400, detail="Empty policy body")

    # Use the policy's relative path as OPA's policy id so subsequent
    # validations and deletes target the same bundle entry.
    ok, err = await opa_admin.validate_with_opa(path, rego)
    if not ok:
        raise HTTPException(status_code=400, detail=f"OPA rejected policy: {err}")

    try:
        opa_admin.write_policy(path, rego)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"policy saved: {path} by {_caller(request)}")
    return {"saved": path, "ok": True}


@router.delete("/{path:path}")
async def delete_policy(path: str, request: Request) -> dict:
    _require_admin(request)
    try:
        await opa_admin.delete_policy(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Policy not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(f"policy deleted: {path} by {_caller(request)}")
    return {"deleted": path}


@router.post("/eval")
async def evaluate(request: Request, payload: dict = Body(...)) -> dict:
    """Dry-run an OPA query. Payload: { query_path: 'insidellm.policy.decision',
    input: { ... } }"""
    _require_admin(request)
    query_path = payload.get("query_path") or "insidellm/policy/decision"
    input_doc = payload.get("input") or {}
    try:
        result = await opa_admin.evaluate(query_path, input_doc)
        return {"query_path": query_path, "result": result}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
