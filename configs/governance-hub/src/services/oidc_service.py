"""
OIDC service — OpenID Connect discovery, authorization, and token exchange.

Handles the OAuth 2.0 Authorization Code flow for Azure AD and Okta.
Caches the OIDC discovery document and JWKS to avoid repeated fetches.
"""

import hashlib
import logging
import secrets
import time

import httpx
from jose import jwt as jose_jwt
from jose.exceptions import JWTError

from ..config import settings

logger = logging.getLogger("governance-hub.oidc")

_oidc_config_cache: dict | None = None
_oidc_config_time: float = 0
_jwks_cache: dict | None = None
_jwks_time: float = 0
CACHE_TTL = 3600  # 1 hour


async def get_oidc_config() -> dict:
    """Fetch and cache the OIDC discovery document."""
    global _oidc_config_cache, _oidc_config_time
    if _oidc_config_cache and (time.monotonic() - _oidc_config_time) < CACHE_TTL:
        return _oidc_config_cache

    issuer = settings.oidc_issuer_url.rstrip("/")
    url = f"{issuer}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _oidc_config_cache = resp.json()
        _oidc_config_time = time.monotonic()
        return _oidc_config_cache


async def get_jwks() -> dict:
    """Fetch and cache the JWKS (JSON Web Key Set)."""
    global _jwks_cache, _jwks_time
    if _jwks_cache and (time.monotonic() - _jwks_time) < CACHE_TTL:
        return _jwks_cache

    config = await get_oidc_config()
    jwks_uri = config["jwks_uri"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_time = time.monotonic()
        return _jwks_cache


def generate_state() -> str:
    """Generate a random state parameter for OIDC."""
    return secrets.token_urlsafe(32)


async def get_authorization_url(redirect_uri: str, state: str) -> str:
    """Build the IdP authorization redirect URL."""
    config = await get_oidc_config()
    auth_endpoint = config["authorization_endpoint"]
    params = {
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": secrets.token_urlsafe(16),
    }
    query = "&".join(f"{k}={httpx.URL('', params={k: v}).params[k]}" for k, v in params.items())
    return f"{auth_endpoint}?{query}"


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for tokens."""
    config = await get_oidc_config()
    token_endpoint = config["token_endpoint"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def validate_id_token(id_token: str) -> dict | None:
    """Validate an OIDC id_token using the IdP's JWKS. Returns claims or None."""
    try:
        jwks = await get_jwks()
        # Decode header to find the key ID
        header = jose_jwt.get_unverified_header(id_token)
        kid = header.get("kid")

        # Find the matching key
        rsa_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = key
                break

        if not rsa_key:
            logger.error(f"JWKS key {kid} not found")
            return None

        claims = jose_jwt.decode(
            id_token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.oidc_client_id,
            options={"verify_at_hash": False},  # Not all IdPs include at_hash
        )
        return claims

    except JWTError as e:
        logger.error(f"ID token validation failed: {e}")
        return None
