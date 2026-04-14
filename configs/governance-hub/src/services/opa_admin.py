"""OPA filesystem + REST admin helpers.

The policy editor reads/writes .rego files under /opa-policies (the same
host directory OPA serves with --watch), and validates each save by
asking OPA to parse the rego before we touch disk.

Validation strategy:
  PUT /v1/policies/<id>  -- OPA returns 400 with parser errors if rego is
                            malformed; 200 if accepted. We use OPA itself
                            as the linter so we don't depend on a separate
                            opa CLI binary inside this container.

Dry-run evaluation:
  POST /v1/data/<package_path>  -- send sample input, get the decision.

Hot-reload happens automatically because OPA runs with --watch on the same
directory we write to.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("insidellm.opa_admin")

OPA_URL = os.environ.get("OPA_URL", "http://opa:8181")
POLICIES_DIR = Path(os.environ.get("OPA_POLICIES_DIR", "/opa-policies"))

# Reject filenames that aren't safe rego files. Allows subdirs (humility/,
# industry/) but not absolute paths or .. traversal.
SAFE_PATH = re.compile(r"^[a-z0-9_][a-z0-9_/-]*\.rego$", re.IGNORECASE)
PACKAGE_DECL = re.compile(r"^\s*package\s+([a-zA-Z0-9_.]+)", re.MULTILINE)


def _resolve(rel_path: str) -> Path:
    """Validate a caller-supplied relative path and return a concrete Path."""
    if not rel_path or rel_path.startswith("/") or ".." in rel_path:
        raise ValueError(f"Unsafe policy path: {rel_path!r}")
    if not SAFE_PATH.match(rel_path):
        raise ValueError(
            f"Policy path must match {SAFE_PATH.pattern}, got {rel_path!r}"
        )
    p = (POLICIES_DIR / rel_path).resolve()
    if not str(p).startswith(str(POLICIES_DIR.resolve())):
        raise ValueError(f"Path escapes policies dir: {rel_path!r}")
    return p


def list_policies() -> list[dict[str, Any]]:
    """Walk POLICIES_DIR and return metadata for every .rego file."""
    if not POLICIES_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(POLICIES_DIR.rglob("*.rego")):
        rel = p.relative_to(POLICIES_DIR).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
            pkg_match = PACKAGE_DECL.search(text)
            package = pkg_match.group(1) if pkg_match else ""
            out.append({
                "path": rel,
                "package": package,
                "size_bytes": len(text),
                "lines": text.count("\n") + 1,
            })
        except Exception as exc:
            logger.warning(f"failed to read {rel}: {exc}")
    return out


def read_policy(rel_path: str) -> str:
    p = _resolve(rel_path)
    if not p.exists():
        raise FileNotFoundError(rel_path)
    return p.read_text(encoding="utf-8")


async def validate_with_opa(policy_id: str, rego_text: str) -> tuple[bool, str]:
    """Ask OPA to parse the rego. Returns (ok, error_message)."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.put(
                f"{OPA_URL}/v1/policies/{policy_id}",
                content=rego_text.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
            )
        except httpx.HTTPError as exc:
            return False, f"OPA unreachable: {exc}"
        if resp.status_code == 200:
            return True, ""
        try:
            body = resp.json()
            return False, body.get("message", resp.text) or resp.text
        except Exception:
            return False, resp.text or f"HTTP {resp.status_code}"


def write_policy(rel_path: str, rego_text: str) -> None:
    p = _resolve(rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(rego_text, encoding="utf-8")


async def delete_policy(rel_path: str) -> None:
    p = _resolve(rel_path)
    if not p.exists():
        raise FileNotFoundError(rel_path)

    # Also remove from OPA's in-memory bundle. --watch will catch the
    # filesystem deletion too, but the explicit DELETE makes the removal
    # immediate even if --watch debounces.
    text = p.read_text(encoding="utf-8")
    pkg_match = PACKAGE_DECL.search(text)
    if pkg_match:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                # OPA's policy id we used on PUT was the relative path; use
                # the same here so DELETE matches.
                await client.delete(f"{OPA_URL}/v1/policies/{rel_path}")
            except httpx.HTTPError as exc:
                logger.warning(f"OPA delete failed (will rely on --watch): {exc}")

    p.unlink()


async def evaluate(query_path: str, input_doc: dict | None) -> dict:
    """Run a dry-run evaluation. query_path is dotted package.rule, e.g.
    'insidellm.policy.decision'. Returns OPA's raw {result: ...} response."""
    # Normalize: insidellm.policy.decision -> v1/data/insidellm/policy/decision
    rest_path = query_path.replace(".", "/").strip("/")
    url = f"{OPA_URL}/v1/data/{rest_path}"
    payload = {"input": input_doc or {}}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"OPA eval failed ({resp.status_code}): {resp.text}")
        return resp.json()
