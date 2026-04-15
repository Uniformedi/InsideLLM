"""
Authentication router — protects the Admin Command Center.

Three modes (driven by GOVERNANCE_HUB_ADMIN_AUTH_MODE):
- "oidc": Azure AD / Okta via OpenID Connect
- "ldap": On-premises Active Directory via LDAP bind
- "none": No authentication (admin page is open)

nginx calls GET /auth/validate as an auth_request subrequest.
On 401, nginx redirects the user to GET /auth/login.
"""

import base64
import binascii
import hmac
import logging

from fastapi import APIRouter, Cookie, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..config import settings
from ..db.local_db import AsyncSessionLocal
from ..services.audit_chain import append_event
from ..services.auth_service import (
    COOKIE_NAME,
    create_session_token,
    ldap_authenticate,
    validate_session_token,
)
from ..services.rbac import (
    ALL_ROLES,
    resolve_roles_from_ldap_groups,
    resolve_roles_from_oidc_groups,
)

BREAK_GLASS_USER = "insidellm-admin"

logger = logging.getLogger("governance-hub.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Login page HTML (LDAP mode) ──────────────────────────────────────────────
LOGIN_PAGE = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>InsideLLM — Sign In</title>
<style>
  :root {{ --bg: #0a0e1a; --card: #1a2234; --border: #2a3650; --text: #e2e8f0;
           --dim: #94a3b8; --cyan: #22d3ee; --red: #f87171; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text);
          display:flex; align-items:center; justify-content:center; min-height:100vh; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px;
           padding:40px; width:380px; max-width:90vw; }}
  h1 {{ font-size:20px; margin-bottom:6px; color:var(--cyan); font-family:monospace; }}
  .sub {{ font-size:13px; color:var(--dim); margin-bottom:24px; }}
  label {{ display:block; font-size:12px; color:var(--dim); margin-bottom:4px; font-family:monospace; text-transform:uppercase; }}
  input {{ width:100%; padding:10px 14px; background:var(--bg); border:1px solid var(--border);
           border-radius:6px; color:var(--text); font-size:14px; margin-bottom:16px; }}
  input:focus {{ outline:none; border-color:var(--cyan); }}
  button {{ width:100%; padding:12px; background:var(--cyan); color:var(--bg); border:none;
            border-radius:6px; font-size:14px; font-weight:600; cursor:pointer; }}
  button:hover {{ opacity:0.9; }}
  .err {{ color:var(--red); font-size:13px; margin-bottom:14px; }}
  .domain {{ color:var(--dim); font-size:12px; font-family:monospace; margin-top:12px; text-align:center; }}
</style>
</head><body>
<div class="card">
  <h1>InsideLLM</h1>
  <div class="sub">Sign in with your {domain_label} credentials</div>
  {error_html}
  <form method="POST" action="/auth/login">
    <label>Username</label>
    <input type="text" name="username" placeholder="{username_hint}" autofocus required>
    <label>Password</label>
    <input type="password" name="password" required>
    <button type="submit">Sign In</button>
  </form>
  <div class="domain">{domain_display}</div>
</div>
</body></html>"""


def _render_login(error: str = "") -> HTMLResponse:
    """Render the LDAP login page."""
    domain = settings.ad_domain
    error_html = f'<div class="err">{error}</div>' if error else ""
    return HTMLResponse(LOGIN_PAGE.format(
        domain_label=domain or "domain",
        username_hint=f"jsmith or jsmith@{domain}" if domain else "username",
        domain_display=domain or "",
        error_html=error_html,
    ))


# ── Break-glass (local admin) ────────────────────────────────────────────────

async def _try_break_glass_basic(request: Request) -> str | None:
    """
    If the request carries Authorization: Basic insidellm-admin:<LITELLM_MASTER_KEY>,
    mint a JWT with all roles, log to governance audit chain, and return the token.
    Returns None if break-glass does not apply.
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None

    master_key = settings.litellm_master_key or ""
    if not master_key:
        return None

    try:
        raw = base64.b64decode(header.split(" ", 1)[1].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None

    if ":" not in raw:
        return None
    user, _, pw = raw.partition(":")
    if user != BREAK_GLASS_USER:
        return None
    # Constant-time compare
    if not hmac.compare_digest(pw, master_key):
        logger.warning("Break-glass login rejected: bad password")
        return None

    token = create_session_token(
        username=BREAK_GLASS_USER,
        groups=["break-glass"],
        roles=list(ALL_ROLES),
        email="",
        name="InsideLLM Break-Glass Admin",
    )

    client_ip = request.client.host if request.client else "unknown"
    logger.info(f"Break-glass login: user={BREAK_GLASS_USER} ip={client_ip}")

    # Best-effort audit chain insert
    try:
        async with AsyncSessionLocal() as db:
            await append_event(
                db,
                event_type="break_glass_login",
                event_id=None,
                payload={
                    "user": BREAK_GLASS_USER,
                    "ip": client_ip,
                    "user_agent": request.headers.get("user-agent", ""),
                },
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to record break-glass audit event: {e}")

    return token


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/validate")
async def validate(request: Request):
    """
    nginx auth_request target. Returns 200 if authenticated, 401 otherwise.
    Sets X-Auth-User header on success for downstream use.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return Response(status_code=401)

    claims = validate_session_token(token)
    if not claims:
        return Response(status_code=401)

    return Response(status_code=200, headers={"X-Auth-User": claims.get("sub", "")})


@router.get("/login")
async def login_page(request: Request):
    """
    Show login UI. OIDC mode redirects to IdP. LDAP mode shows a form.
    """
    mode = settings.admin_auth_mode

    if mode == "oidc":
        from ..services.oidc_service import generate_state, get_authorization_url
        state = generate_state()
        # Build redirect URI from the request
        scheme = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("host", "localhost")
        redirect_uri = f"{scheme}://{host}/auth/callback"
        auth_url = await get_authorization_url(redirect_uri, state)
        response = RedirectResponse(auth_url, status_code=302)
        response.set_cookie("oidc_state", state, httponly=True, secure=True, samesite="lax", max_age=600)
        return response

    if mode == "ldap":
        return _render_login()

    # mode == "none" — shouldn't reach here, but just redirect to admin
    return RedirectResponse("/admin", status_code=302)


@router.post("/login")
async def login_submit(request: Request, username: str = Form(None), password: str = Form(None)):
    """
    Login submission. Try break-glass Basic auth first; then LDAP form flow.
    """
    # Break-glass (Basic auth) — works in any admin_auth_mode, always on.
    bg_token = await _try_break_glass_basic(request)
    if bg_token:
        response = RedirectResponse("/admin", status_code=302)
        response.set_cookie(
            COOKIE_NAME, bg_token,
            httponly=True, secure=True, samesite="lax",
            max_age=8 * 3600, path="/",
        )
        return response

    if settings.admin_auth_mode != "ldap":
        return RedirectResponse("/admin", status_code=302)

    if not username or not password:
        return _render_login("Username and password are required")

    success, groups = ldap_authenticate(username, password)
    if not success:
        return _render_login("Invalid credentials")

    roles = resolve_roles_from_ldap_groups(groups)
    if not roles:
        logger.warning(f"LDAP user {username} denied: no matching RBAC groups (groups={groups})")
        return _render_login("Access denied: your account is not a member of any InsideLLM role group")

    clean_user = username.split("@")[0] if "@" in username else username
    token = create_session_token(clean_user, groups=groups, roles=roles, name=clean_user)
    response = RedirectResponse("/admin", status_code=302)
    response.set_cookie(
        COOKIE_NAME, token,
        httponly=True, secure=True, samesite="lax",
        max_age=8 * 3600,
        path="/",
    )
    return response


@router.post("/token")
async def api_token(request: Request):
    """
    API-friendly login. Supports:
      - Break-glass: Authorization: Basic base64(insidellm-admin:<LITELLM_MASTER_KEY>)
    Returns {access_token, token_type, roles} on success.
    """
    bg_token = await _try_break_glass_basic(request)
    if bg_token:
        return {
            "access_token": bg_token,
            "token_type": "bearer",
            "roles": list(ALL_ROLES),
        }
    return JSONResponse({"detail": "Invalid credentials"}, status_code=401)


@router.get("/callback")
async def oidc_callback(request: Request, code: str = "", state: str = ""):
    """
    OIDC callback — exchanges authorization code for tokens, creates session.
    """
    if settings.admin_auth_mode != "oidc":
        return RedirectResponse("/admin", status_code=302)

    from ..services.oidc_service import exchange_code, validate_id_token

    # Verify state
    stored_state = request.cookies.get("oidc_state", "")
    if not stored_state or stored_state != state:
        return HTMLResponse("Invalid state parameter. <a href='/auth/login'>Try again</a>", status_code=400)

    # Build redirect URI (must match the one used in the authorize request)
    scheme = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("host", "localhost")
    redirect_uri = f"{scheme}://{host}/auth/callback"

    try:
        tokens = await exchange_code(code, redirect_uri)
    except Exception as e:
        logger.error(f"OIDC code exchange failed: {e}")
        return HTMLResponse(f"Authentication failed: {e}. <a href='/auth/login'>Try again</a>", status_code=400)

    id_token = tokens.get("id_token")
    if not id_token:
        return HTMLResponse("No id_token in response. <a href='/auth/login'>Try again</a>", status_code=400)

    claims = await validate_id_token(id_token)
    if not claims:
        return HTMLResponse("Token validation failed. <a href='/auth/login'>Try again</a>", status_code=400)

    # Extract user info
    username = claims.get("preferred_username") or claims.get("email") or claims.get("sub", "unknown")
    email = claims.get("email", "")
    display_name = claims.get("name", "") or username
    groups = claims.get("groups", []) or []

    roles = resolve_roles_from_oidc_groups(groups)
    if not roles:
        logger.warning(f"OIDC user {username} denied: no matching RBAC groups (groups={groups})")
        return HTMLResponse(
            "Access denied: your account is not a member of any InsideLLM role group. "
            "<a href='/auth/login'>Try again</a>",
            status_code=403,
        )

    token = create_session_token(username, groups=groups, roles=roles, email=email, name=display_name)
    response = RedirectResponse("/admin", status_code=302)
    response.set_cookie(
        COOKIE_NAME, token,
        httponly=True, secure=True, samesite="lax",
        max_age=8 * 3600,
        path="/",
    )
    response.delete_cookie("oidc_state")
    return response


@router.post("/logout")
@router.get("/logout")
async def logout():
    """Clear session cookie and redirect to admin (which will trigger login)."""
    response = RedirectResponse("/admin", status_code=302)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/whoami")
async def whoami(request: Request):
    """Return the current authenticated user (for the admin UI topbar)."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return {"authenticated": False}

    claims = validate_session_token(token)
    if not claims:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "username": claims.get("sub", ""),
        "email": claims.get("email", ""),
        "name": claims.get("name", ""),
        "groups": claims.get("groups", []),
        "roles": claims.get("roles", []),
    }
