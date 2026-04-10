"""
Terraform.tfvars vault — encrypted storage for deployment configurations.

Uses AES-256-GCM encryption with the governance hub_secret as the key.
Stored in the local DB (governance_deployment_tfvars) and synced to the
central fleet DB for cross-instance cloning.

The tfvars data is NOT readable through direct SQL queries — it must be
decrypted through this service using the hub_secret.
"""

import base64
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import DeploymentTfvars

logger = logging.getLogger("governance-hub.tfvars-vault")

# Path where cloud-init drops the pending tfvars file
PENDING_TFVARS_PATH = "/app/data/.deployment-tfvars-pending"


def _derive_key(secret: str) -> bytes:
    """Derive a 256-bit AES key from the hub_secret using SHA-256."""
    return hashlib.sha256(secret.encode()).digest()


def encrypt_tfvars(tfvars_text: str) -> tuple[str, str]:
    """Encrypt tfvars text using AES-256-GCM. Returns (encrypted_b64, iv_b64)."""
    key = _derive_key(settings.hub_secret or settings.auth_secret or "insidellm-default-key")
    iv = os.urandom(12)  # 96-bit nonce for GCM
    aesgcm = AESGCM(key)
    encrypted = aesgcm.encrypt(iv, tfvars_text.encode("utf-8"), None)
    return base64.b64encode(encrypted).decode(), base64.b64encode(iv).decode()


def decrypt_tfvars(encrypted_b64: str, iv_b64: str) -> str:
    """Decrypt tfvars text using AES-256-GCM. Returns plaintext."""
    key = _derive_key(settings.hub_secret or settings.auth_secret or "insidellm-default-key")
    iv = base64.b64decode(iv_b64)
    encrypted = base64.b64decode(encrypted_b64)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, encrypted, None).decode("utf-8")


def store_deployment_tfvars(db: Session, tfvars_text: str) -> dict:
    """Encrypt and store (or update) the deployment tfvars in the local DB."""
    encrypted, iv = encrypt_tfvars(tfvars_text)

    # Check if we already have a record for this instance
    existing = db.execute(
        text("SELECT id FROM governance_deployment_tfvars WHERE instance_id = :iid"),
        {"iid": settings.instance_id},
    ).first()

    if existing:
        db.execute(
            text("""UPDATE governance_deployment_tfvars
                SET encrypted_tfvars = :enc, encryption_iv = :iv,
                    platform_version = :ver, updated_at = :now
                WHERE instance_id = :iid"""),
            {"enc": encrypted, "iv": iv, "ver": settings.platform_version,
             "now": datetime.now(timezone.utc), "iid": settings.instance_id},
        )
    else:
        record = DeploymentTfvars(
            instance_id=settings.instance_id,
            platform_version=settings.platform_version,
            encrypted_tfvars=encrypted,
            encryption_iv=iv,
        )
        db.add(record)

    db.commit()
    logger.info(f"Deployment tfvars stored (encrypted, {len(tfvars_text)} chars)")
    return {"success": True, "chars": len(tfvars_text)}


def retrieve_deployment_tfvars(db: Session, instance_id: str | None = None) -> str | None:
    """Decrypt and return the stored deployment tfvars for an instance."""
    iid = instance_id or settings.instance_id
    result = db.execute(
        text("SELECT encrypted_tfvars, encryption_iv FROM governance_deployment_tfvars WHERE instance_id = :iid"),
        {"iid": iid},
    ).first()

    if not result:
        return None

    try:
        return decrypt_tfvars(result[0], result[1])
    except Exception as e:
        logger.error(f"Failed to decrypt tfvars for {iid}: {e}")
        return None


def ingest_pending_tfvars(db: Session) -> bool:
    """Read the pending tfvars file from cloud-init, encrypt and store, then delete.

    Called on startup. Returns True if a file was ingested.
    """
    pending = Path(PENDING_TFVARS_PATH)
    if not pending.exists():
        return False

    try:
        tfvars_text = pending.read_text(encoding="utf-8").strip()
        if not tfvars_text:
            pending.unlink()
            return False

        store_deployment_tfvars(db, tfvars_text)
        pending.unlink()  # Delete the plaintext file after encrypting
        logger.info("Ingested and encrypted pending deployment tfvars")
        return True
    except Exception as e:
        logger.error(f"Failed to ingest pending tfvars: {e}")
        return False


def sanitize_for_clone(tfvars_text: str) -> str:
    """Sanitize a tfvars string for cloning — replace secrets with CHANGE_ME."""
    # Replace known secret patterns
    secret_keys = [
        "anthropic_api_key", "hyperv_password", "litellm_master_key",
        "postgres_password", "azure_ad_client_secret", "okta_client_secret",
        "ad_join_password",
    ]
    result = tfvars_text
    for key in secret_keys:
        # Match: key = "value" or key = "REDACTED"
        result = re.sub(
            rf'^({key}\s*=\s*)"[^"]*"',
            rf'\1"CHANGE_ME"',
            result,
            flags=re.MULTILINE,
        )

    # Also replace any remaining REDACTED markers
    result = result.replace('"REDACTED"', '"CHANGE_ME"')

    return result


def merge_with_new_variables(original_tfvars: str, current_version_defaults: dict) -> str:
    """Merge an older tfvars with new variables added in later versions.

    Variables in the original are preserved. New variables from
    current_version_defaults that don't exist in the original are appended.
    """
    # Parse existing variable names from the original
    existing_keys = set()
    for line in original_tfvars.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=")[0].strip()
            existing_keys.add(key)

    # Find new variables not in the original
    new_vars = {k: v for k, v in current_version_defaults.items() if k not in existing_keys}

    if not new_vars:
        return original_tfvars

    lines = [original_tfvars.rstrip()]
    lines.append("")
    lines.append("# =========================================================================")
    lines.append(f"# New variables added in v{settings.platform_version}")
    lines.append("# =========================================================================")
    for key, value in sorted(new_vars.items()):
        if isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        else:
            lines.append(f"{key} = {value}")

    lines.append("")
    return "\n".join(lines)


# Variables added in each version — used for merging during clone
VERSION_VARIABLE_ADDITIONS = {
    "3.1.0": {
        "ad_admin_groups": "Domain Admins",
    },
}


def get_current_version_defaults() -> dict:
    """Aggregate all new variables across versions for merge."""
    defaults = {}
    for version, vars in sorted(VERSION_VARIABLE_ADDITIONS.items()):
        defaults.update(vars)
    return defaults
