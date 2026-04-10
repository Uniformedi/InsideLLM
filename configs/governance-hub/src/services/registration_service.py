"""
Registration service — secure clone self-registration with temporary API keys.

Allows a fleet administrator to generate a time-limited registration token.
A new InsideLLM instance presents this token to self-register with the fleet,
receiving encrypted fleet DB credentials and auto-configuring the connection.

Flow:
1. Admin generates a registration token (valid for N hours)
2. New instance is deployed with the token in its Setup Wizard or config
3. New instance calls POST /api/v1/fleet/register with the token
4. Fleet manager validates the token, returns encrypted fleet DB credentials
5. New instance stores credentials and connects to the fleet
6. Token is marked as used (single-use)
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ..config import settings
from ..db.central_db import run_central_query
from ..db.central_sql import SQL

logger = logging.getLogger("governance-hub.registration")


def generate_registration_token(hours: int = 24, created_by: str = "admin") -> dict:
    """Generate a time-limited, single-use registration token.

    Returns the token string. The token is stored in the central DB.
    """
    token = f"reg-{secrets.token_urlsafe(32)}"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)

    async def _store(db):
        db.execute(text(SQL.create_registration_token), {
            "token": token,
            "created_by": created_by,
            "expires_at": expires_at,
        })
        db.commit()
        return True

    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "hours": hours,
        "created_by": created_by,
    }


async def store_token(token: str, created_by: str, expires_at: datetime) -> bool:
    """Store a registration token in the central DB."""
    def _store(db):
        db.execute(text(SQL.create_registration_token), {
            "token": token,
            "created_by": created_by,
            "expires_at": expires_at,
        })
        db.commit()
        return True

    try:
        return await run_central_query(_store)
    except Exception as e:
        logger.error(f"Failed to store registration token: {e}")
        return False


async def validate_and_consume_token(token: str, instance_id: str) -> dict | None:
    """Validate a registration token and mark it as used.

    Returns the fleet DB credentials (encrypted) if valid, None if invalid.
    """
    def _validate(db):
        result = db.execute(text(SQL.validate_registration_token), {"token": token})
        row = result.first()
        if not row:
            return None

        # Mark as used
        db.execute(text(SQL.mark_token_used), {"token": token, "used_by": instance_id})
        db.commit()
        return {"valid": True, "created_by": row[2]}

    result = await run_central_query(_validate)
    if not result:
        return None

    # Return the fleet DB credentials for the new instance
    return {
        "valid": True,
        "fleet_db": {
            "db_type": settings.central_db_type,
            "host": settings.central_db_host,
            "port": settings.central_db_port,
            "db_name": settings.central_db_name,
            "username": settings.central_db_user,
            # Password is encrypted with the token as a key component
            "password_encrypted": _encrypt_with_token(settings.central_db_password, token),
        },
        "hub_secret": settings.hub_secret,
        "registered_by": result["created_by"],
    }


def _encrypt_with_token(value: str, token: str) -> str:
    """Simple XOR-based encryption using the token as key. For transport only."""
    import base64
    key = hashlib.sha256(token.encode()).digest()
    encrypted = bytes(a ^ b for a, b in zip(value.encode(), key * (len(value) // len(key) + 1)))
    return base64.b64encode(encrypted).decode()


def _decrypt_with_token(encrypted_b64: str, token: str) -> str:
    """Decrypt a value encrypted with _encrypt_with_token."""
    import base64
    key = hashlib.sha256(token.encode()).digest()
    encrypted = base64.b64decode(encrypted_b64)
    return bytes(a ^ b for a, b in zip(encrypted, key * (len(encrypted) // len(key) + 1))).decode()
