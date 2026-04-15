"""
Authentication service — JWT session management and LDAP/AD authentication.

Supports two auth backends:
- LDAP: Binds to Active Directory using the user's own credentials (UPN format),
  then checks group membership against the allowed admin groups.
- OIDC: Session tokens are created after OIDC callback validates the id_token
  (handled by oidc_service.py).

Sessions are stateless JWT cookies signed with auth_secret.
"""

import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from ..config import settings

logger = logging.getLogger("governance-hub.auth")

ALGORITHM = "HS256"
SESSION_HOURS = 8
COOKIE_NAME = "insidellm_session"


def create_session_token(
    username: str,
    groups: list[str] | None = None,
    roles: list[str] | None = None,
    email: str = "",
    name: str = "",
) -> str:
    """Create a signed JWT session token with RBAC roles embedded."""
    payload = {
        "sub": username,
        "email": email,
        "name": name or username,
        "groups": groups or [],
        "roles": roles or [],
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS),
    }
    return jwt.encode(payload, settings.auth_secret or settings.hub_secret, algorithm=ALGORITHM)


def validate_session_token(token: str) -> dict | None:
    """Validate a JWT session token. Returns claims dict or None."""
    try:
        claims = jwt.decode(
            token,
            settings.auth_secret or settings.hub_secret,
            algorithms=[ALGORITHM],
        )
        return claims
    except JWTError:
        return None


def ldap_authenticate(username: str, password: str) -> tuple[bool, list[str]]:
    """
    Authenticate against Active Directory via LDAP.

    Binds as username@DOMAIN using the user's credentials, then searches
    for group membership. Returns (success, list_of_groups).
    """
    try:
        import ldap3
    except ImportError:
        logger.error("ldap3 not installed")
        return False, []

    domain = settings.ad_domain
    if not domain:
        logger.error("AD domain not configured")
        return False, []

    # Build UPN (user@domain.local)
    upn = username if "@" in username else f"{username}@{domain}"

    # Try LDAPS (636) first, fall back to LDAP (389)
    server = None
    for port, use_ssl in [(636, True), (389, False)]:
        try:
            server = ldap3.Server(domain, port=port, use_ssl=use_ssl, get_info=ldap3.DSA, connect_timeout=5)
            conn = ldap3.Connection(server, user=upn, password=password, auto_bind=True, receive_timeout=10)
            break
        except Exception as e:
            logger.debug(f"LDAP connect on port {port} failed: {e}")
            conn = None
            continue

    if conn is None:
        logger.warning(f"LDAP bind failed for {upn}")
        return False, []

    try:
        # Build base DN from domain (e.g., uniformedi.local -> DC=uniformedi,DC=local)
        base_dn = ",".join(f"DC={part}" for part in domain.split("."))

        # Search for the user's groups
        search_filter = f"(&(objectClass=user)(userPrincipalName={upn}))"
        conn.search(base_dn, search_filter, attributes=["memberOf", "cn", "sAMAccountName"])

        if not conn.entries:
            # Try sAMAccountName if UPN search failed
            sam = username.split("@")[0] if "@" in username else username
            search_filter = f"(&(objectClass=user)(sAMAccountName={sam}))"
            conn.search(base_dn, search_filter, attributes=["memberOf", "cn"])

        groups: list[str] = []
        if conn.entries:
            entry = conn.entries[0]
            raw_groups = entry.memberOf.values if hasattr(entry, "memberOf") and entry.memberOf else []
            for g in raw_groups:
                # Extract CN from DN: "CN=Domain Admins,CN=Users,DC=..."
                for part in str(g).split(","):
                    if part.strip().upper().startswith("CN="):
                        groups.append(part.strip()[3:])
                        break

        # Return all resolved groups; RBAC role mapping happens in rbac.py
        logger.info(f"LDAP auth success: {upn}, groups: {groups}")
        return True, groups

    except Exception as e:
        logger.error(f"LDAP search error: {e}")
        return False, []
    finally:
        conn.unbind()
