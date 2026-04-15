"""
Role-based access control for the Governance Hub.

Three roles:
  - view      : GET-only across all routes
  - admin     : CRUD everywhere except change approve/reject
  - approver  : POST /api/v1/changes/{id}/approve|reject

Role sources (union):
  - LDAP memberOf  CN values compared to ad_*_groups (case-insensitive)
  - OIDC groups claim compared to oidc_*_group_ids
  - Break-glass local account always carries [admin, approver, view]

Backcompat: if ad_view_groups / ad_approver_groups are empty but ad_admin_groups
is populated, any user in ad_admin_groups receives all three roles (legacy
single-group gate). A WARNING is logged the first time this fires.
"""

import logging

from fastapi import Depends, HTTPException, Request

from ..config import settings
from .auth_service import COOKIE_NAME, validate_session_token

logger = logging.getLogger("governance-hub.rbac")

ROLE_VIEW = "view"
ROLE_ADMIN = "admin"
ROLE_APPROVER = "approver"
ALL_ROLES = [ROLE_ADMIN, ROLE_APPROVER, ROLE_VIEW]

_legacy_warned = False


def _match_ci(user_groups: list[str], allowed: list[str]) -> bool:
    """Case-insensitive membership check."""
    uset = {g.lower() for g in user_groups}
    aset = {g.lower() for g in allowed if g}
    return bool(aset & uset)


def resolve_roles_from_ldap_groups(groups: list[str]) -> list[str]:
    """
    Map AD CN-based group names to roles. Applies legacy backcompat fallback
    when only ad_admin_groups is configured.
    """
    global _legacy_warned

    view_allowed = settings.ad_view_group_list
    admin_allowed = settings.ad_admin_group_list
    approver_allowed = settings.ad_approver_group_list

    # Backcompat: legacy single-group gate
    if admin_allowed and not view_allowed and not approver_allowed:
        if not _legacy_warned:
            logger.warning(
                "RBAC legacy fallback active: ad_admin_groups set but "
                "ad_view_groups / ad_approver_groups empty. All users in "
                "ad_admin_groups granted admin+approver+view."
            )
            _legacy_warned = True
        if _match_ci(groups, admin_allowed):
            return list(ALL_ROLES)
        return []

    roles: set[str] = set()
    if _match_ci(groups, view_allowed):
        roles.add(ROLE_VIEW)
    if _match_ci(groups, admin_allowed):
        roles.add(ROLE_ADMIN)
        roles.add(ROLE_VIEW)  # admin implies view
    if _match_ci(groups, approver_allowed):
        roles.add(ROLE_APPROVER)
        roles.add(ROLE_VIEW)  # approver implies view
    return sorted(roles)


def resolve_roles_from_oidc_groups(group_claim: list[str]) -> list[str]:
    """Map OIDC group GUIDs (or names) to roles."""
    view_allowed = settings.oidc_view_group_id_list
    admin_allowed = settings.oidc_admin_group_id_list
    approver_allowed = settings.oidc_approver_group_id_list

    roles: set[str] = set()
    if _match_ci(group_claim, view_allowed):
        roles.add(ROLE_VIEW)
    if _match_ci(group_claim, admin_allowed):
        roles.add(ROLE_ADMIN)
        roles.add(ROLE_VIEW)
    if _match_ci(group_claim, approver_allowed):
        roles.add(ROLE_APPROVER)
        roles.add(ROLE_VIEW)
    return sorted(roles)


def get_roles_from_request(request: Request) -> list[str]:
    """Read roles from the session JWT; empty list if unauthenticated."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        # Also accept bearer for API clients (same signing key)
        auth_hdr = request.headers.get("authorization", "")
        if auth_hdr.lower().startswith("bearer "):
            token = auth_hdr.split(" ", 1)[1].strip()
    if not token:
        return []
    claims = validate_session_token(token)
    if not claims:
        return []
    return list(claims.get("roles") or [])


def require_role(role: str):
    """FastAPI dependency factory — enforces presence of the given role."""

    async def _dep(request: Request) -> list[str]:
        roles = get_roles_from_request(request)
        if role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: '{role}' role required",
            )
        return roles

    return _dep


# Pre-built dependency instances (use with Depends())
require_view = Depends(require_role(ROLE_VIEW))
require_admin = Depends(require_role(ROLE_ADMIN))
require_approver = Depends(require_role(ROLE_APPROVER))


# ── Method-based enforcement middleware ───────────────────────────────────────

# Paths that bypass RBAC entirely (login flow, nginx subrequest, health, landing).
_EXEMPT_PREFIXES = (
    "/auth/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)
_EXEMPT_EXACT = {"/", "/health"}

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _is_exempt(path: str) -> bool:
    if path in _EXEMPT_EXACT:
        return True
    return any(path.startswith(p) for p in _EXEMPT_PREFIXES)


async def rbac_middleware(request: Request, call_next):
    """
    Global RBAC gate keyed by HTTP method.

    - Exempt paths: auth, health, docs, landing.
    - Safe methods (GET/HEAD/OPTIONS): require 'view'.
    - Mutations: require 'admin' (approve/reject override to 'approver'
      is enforced explicitly in the changes router via require_approver).
    """
    from starlette.responses import JSONResponse

    # Skip if auth is disabled
    if settings.admin_auth_mode == "none":
        return await call_next(request)

    path = request.url.path
    if _is_exempt(path):
        return await call_next(request)

    roles = get_roles_from_request(request)
    if not roles:
        return JSONResponse({"detail": "Unauthenticated"}, status_code=401)

    method = request.method.upper()
    needed = ROLE_VIEW if method in _SAFE_METHODS else ROLE_ADMIN
    if needed not in roles:
        return JSONResponse(
            {"detail": f"Forbidden: '{needed}' role required"},
            status_code=403,
        )

    return await call_next(request)
