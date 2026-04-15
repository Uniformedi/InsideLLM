"""
Framework router — serves parsed governance framework sections, compliance
status, attestations, and triggers compliance checks.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..db.models import ComplianceAttestation, ComplianceStatus, FrameworkSection
from ..middleware.auth import verify_api_key

router = APIRouter(prefix="/api/v1/framework", tags=["framework"])


# ── Schemas ───────────────────────────────────────────────────────────────

class AttestationRequest(BaseModel):
    section_id: int
    attester_name: str
    attester_email: str
    attester_role: str = ""
    attestation_text: str
    valid_days: int = 90


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/sections")
async def list_sections(
    version: int = 1,
    db: AsyncSession = Depends(get_local_db),
):
    """List all framework sections with latest compliance status."""
    result = await db.execute(text("""
        SELECT s.id, s.section_number, s.title, s.parent_section,
               s.compliance_type, s.automated_check_key, s.sort_order,
               cs.status AS compliance_status, cs.assessed_at, cs.evidence_type, cs.notes
        FROM governance_framework_sections s
        LEFT JOIN LATERAL (
            SELECT status, assessed_at, evidence_type, notes
            FROM governance_compliance_status
            WHERE section_id = s.id
            ORDER BY assessed_at DESC LIMIT 1
        ) cs ON true
        WHERE s.framework_version = :v
        ORDER BY s.sort_order
    """), {"v": version})

    sections = []
    for row in result.mappings():
        sections.append({
            "id": row["id"],
            "section_number": row["section_number"],
            "title": row["title"],
            "parent_section": row["parent_section"],
            "compliance_type": row["compliance_type"],
            "automated_check_key": row["automated_check_key"],
            "compliance_status": row["compliance_status"] or "not_assessed",
            "assessed_at": row["assessed_at"].isoformat() if row["assessed_at"] else None,
            "evidence_type": row["evidence_type"],
        })

    return {"sections": sections, "total": len(sections)}


@router.get("/tree")
async def section_tree(
    version: int = 1,
    db: AsyncSession = Depends(get_local_db),
):
    """Hierarchical tree of framework sections for sidebar navigation."""
    result = await db.execute(text("""
        SELECT s.id, s.section_number, s.title, s.parent_section,
               s.compliance_type, s.sort_order,
               cs.status AS compliance_status
        FROM governance_framework_sections s
        LEFT JOIN LATERAL (
            SELECT status
            FROM governance_compliance_status
            WHERE section_id = s.id
            ORDER BY assessed_at DESC LIMIT 1
        ) cs ON true
        WHERE s.framework_version = :v
        ORDER BY s.sort_order
    """), {"v": version})

    all_sections = [dict(row) for row in result.mappings()]

    # Build tree: top-level sections with children
    top_level = [s for s in all_sections if not s["parent_section"]]
    for parent in top_level:
        parent["children"] = [
            s for s in all_sections if s["parent_section"] == parent["section_number"]
        ]

    return {"tree": top_level}


@router.get("/sections/{section_number}")
async def get_section(
    section_number: str,
    version: int = 1,
    db: AsyncSession = Depends(get_local_db),
):
    """Get a single section with full content, compliance history, and attestations."""
    result = await db.execute(text("""
        SELECT * FROM governance_framework_sections
        WHERE section_number = :sn AND framework_version = :v
    """), {"sn": section_number, "v": version})
    section = result.mappings().first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")

    section_dict = dict(section)
    sid = section_dict["id"]

    # Compliance history
    history = await db.execute(text("""
        SELECT status, evidence_type, evidence_details, assessed_by, assessed_at, notes
        FROM governance_compliance_status
        WHERE section_id = :sid
        ORDER BY assessed_at DESC LIMIT 10
    """), {"sid": sid})
    section_dict["compliance_history"] = [dict(r) for r in history.mappings()]

    # Attestations
    attestations = await db.execute(text("""
        SELECT attester_name, attester_role, attestation_text, status, attested_at, expires_at
        FROM governance_compliance_attestations
        WHERE section_id = :sid
        ORDER BY attested_at DESC LIMIT 10
    """), {"sid": sid})
    section_dict["attestations"] = [dict(r) for r in attestations.mappings()]

    return section_dict


@router.get("/compliance/summary")
async def compliance_summary(
    version: int = 1,
    db: AsyncSession = Depends(get_local_db),
):
    """Aggregate compliance status across all framework sections."""
    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total_sections,
            COUNT(*) FILTER (WHERE s.compliance_type != 'informational') AS assessable,
            COUNT(*) FILTER (WHERE cs.status = 'compliant') AS compliant,
            COUNT(*) FILTER (WHERE cs.status = 'non_compliant') AS non_compliant,
            COUNT(*) FILTER (WHERE cs.status = 'partial') AS partial,
            COUNT(*) FILTER (WHERE cs.status = 'not_assessed' OR cs.status IS NULL) AS not_assessed,
            COUNT(*) FILTER (WHERE cs.status = 'check_failed') AS check_failed,
            COUNT(*) FILTER (WHERE s.compliance_type = 'automated') AS automated_count,
            COUNT(*) FILTER (WHERE s.compliance_type = 'manual_attestation') AS manual_count,
            COUNT(*) FILTER (WHERE s.compliance_type = 'informational') AS informational_count
        FROM governance_framework_sections s
        LEFT JOIN LATERAL (
            SELECT status
            FROM governance_compliance_status
            WHERE section_id = s.id
            ORDER BY assessed_at DESC LIMIT 1
        ) cs ON true
        WHERE s.framework_version = :v
    """), {"v": version})

    row = result.mappings().first()
    assessable = row["assessable"] or 1
    compliant = row["compliant"] or 0
    pct = round(compliant / assessable * 100, 1) if assessable > 0 else 0

    return {
        "total_sections": row["total_sections"],
        "assessable_sections": assessable,
        "compliance_percentage": pct,
        "compliant": compliant,
        "non_compliant": row["non_compliant"] or 0,
        "partial": row["partial"] or 0,
        "not_assessed": row["not_assessed"] or 0,
        "check_failed": row["check_failed"] or 0,
        "automated_count": row["automated_count"] or 0,
        "manual_count": row["manual_count"] or 0,
        "informational_count": row["informational_count"] or 0,
    }


@router.post("/compliance/attest")
async def submit_attestation(
    req: AttestationRequest,
    db: AsyncSession = Depends(get_local_db),
):
    """Submit a manual attestation for a framework section."""
    # Verify section exists
    section = await db.execute(text(
        "SELECT id, compliance_type FROM governance_framework_sections WHERE id = :sid"
    ), {"sid": req.section_id})
    row = section.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Section not found")

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=req.valid_days)

    # Create attestation
    attestation = ComplianceAttestation(
        section_id=req.section_id,
        attester_name=req.attester_name,
        attester_email=req.attester_email,
        attester_role=req.attester_role,
        attestation_text=req.attestation_text,
        attested_at=now,
        expires_at=expires,
    )
    db.add(attestation)

    # Update compliance status
    status = ComplianceStatus(
        section_id=req.section_id,
        status="compliant",
        evidence_type="manual_attestation",
        evidence_details={
            "attester": req.attester_name,
            "role": req.attester_role,
            "text": req.attestation_text[:200],
        },
        assessed_by=req.attester_name,
        assessed_at=now,
        expires_at=expires,
        notes=f"Attested by {req.attester_name} ({req.attester_role})",
    )
    db.add(status)
    await db.commit()

    return {"success": True, "message": f"Attestation recorded, expires {expires.date()}"}


@router.post("/seed")
async def seed_framework(db: AsyncSession = Depends(get_local_db)):
    """Parse and seed framework sections.

    Source precedence:
      1. Central fleet DB (governance_framework_documents) — preferred;
         ensures every instance in a fleet runs the same version.
      2. Local file at settings.framework_path — fallback for legacy
         deployments where the markdown was bundled in at deploy time.
    Returns success:false with a clear message when neither source has
    content, so the admin UI can show the Upload button instead of
    looking broken.
    """
    from ..services.framework_parser import seed_framework_sections
    from ..services.fleet_service import get_current_framework_document
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from ..db.local_db import SyncSessionLocal

    central_doc = await get_current_framework_document()
    content = central_doc["content"] if central_doc else None

    def _seed():
        with SyncSessionLocal() as sync_db:
            return seed_framework_sections(sync_db, content=content)

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, _seed)

    if central_doc and result.get("success"):
        result["source"] = "central_db"
        result["document_version"] = central_doc.get("version")
        result["document_sha256"] = central_doc.get("sha256")
    elif result.get("success"):
        result["source"] = "local_file"
    return result


# ── Framework document upload (fleet-wide) ─────────────────────────────────

class FrameworkDocumentUpload(BaseModel):
    content: str
    filename: str | None = None
    note: str | None = None


@router.post("/document")
async def upload_framework_document(payload: FrameworkDocumentUpload):
    """Admin upload endpoint. Stores the markdown in the central Fleet DB
    so every instance in the fleet pulls the same version. Previous
    versions are preserved (version auto-increments)."""
    from ..services.fleet_service import upload_framework_document as _upload
    from ..config import settings

    uploaded_by = "admin"  # Replace with authenticated user from auth middleware
    result = await _upload(
        content=payload.content,
        uploaded_by=uploaded_by,
        instance_id=settings.instance_id or "local",
        filename=payload.filename,
        note=payload.note,
    )
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("message", "Central DB unavailable"))
    return result


@router.get("/document/current")
async def get_current_framework_document():
    """Return the latest framework document from the central fleet DB."""
    from ..services.fleet_service import get_current_framework_document as _get
    doc = await _get()
    if not doc:
        return {"exists": False}
    return {"exists": True, **doc}


@router.get("/document/versions")
async def list_framework_document_versions():
    """List all uploaded framework document versions (content excluded)."""
    from ..services.fleet_service import list_framework_document_versions as _list
    return {"versions": await _list()}
