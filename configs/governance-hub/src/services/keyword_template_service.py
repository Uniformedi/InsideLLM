"""
Keyword template service — manages industry keyword templates in the central fleet DB.

Templates are the canonical set of keyword categories per industry. They are
seeded from SEED_TEMPLATES on first fleet DB initialization, editable via the
admin UI (with governance change tracking), and synced across fleet instances.
"""

import logging

from sqlalchemy import text

from ..config import settings
from ..db.central_db import run_central_query
from ..db.central_sql import SQL

logger = logging.getLogger("governance-hub.keyword-templates")

# =========================================================================
# Seed data — matches INDUSTRY_TEMPLATES from Setup.html
# =========================================================================

SEED_TEMPLATES = {
    "general": {
        "hint": "General-purpose deployment — keyword categories focus on common business use patterns.",
        "tier": "tier3", "classification": "internal", "categories": {}
    },
    "collections": {
        "hint": "Collections & debt recovery — pre-loaded with FDCPA/FCRA/TCPA terms, debtor communications, and regulatory compliance keywords.",
        "tier": "tier1", "classification": "confidential",
        "categories": {
            "collections": "debt, collection, payment plan, settlement, overdue, delinquent, garnishment, repossession, charge-off, creditor, debtor, past due, default, recovery, skip trace, right party contact",
            "consumer-comms": "letter, notice, demand, disclosure, mini-miranda, validation, cease and desist, dispute, hardship, forbearance",
            "regulatory": "fdcpa, fcra, tcpa, ecoa, cfpb, regulation f, regulation b, ftc, consent decree, compliance, audit, examination",
            "financial": "balance, principal, interest, fee, payment, account, credit report, credit score, bureau, tradeline",
        }
    },
    "healthcare": {
        "hint": "Healthcare & medical — HIPAA-aligned keywords for PHI detection, clinical terminology, and patient safety.",
        "tier": "tier1", "classification": "restricted",
        "categories": {
            "hipaa": "hipaa, phi, protected health information, health record, medical record, ehr, emr, patient data, authorization, consent",
            "clinical": "diagnosis, treatment, prescription, medication, procedure, lab result, imaging, radiology, pathology, referral",
            "patient-safety": "adverse event, incident, medication error, allergy, contraindication, fall risk, infection, readmission",
            "billing-medical": "claim, cpt, icd, drg, prior authorization, denial, appeal, reimbursement, copay, deductible, explanation of benefits",
            "compliance-health": "cms, fda, joint commission, stark law, anti-kickback, meaningful use, interoperability, breach notification",
        }
    },
    "financial": {
        "hint": "Financial services & banking — BSA/AML, KYC, lending compliance, and regulatory reporting keywords.",
        "tier": "tier1", "classification": "restricted",
        "categories": {
            "aml-bsa": "aml, bsa, suspicious activity, sar, ctr, money laundering, structuring, smurfing, beneficial owner, ofac, sanctions",
            "kyc": "kyc, know your customer, identity verification, due diligence, enhanced due diligence, pep, politically exposed",
            "lending": "mortgage, loan, underwriting, apr, tila, respa, hmda, redlining, fair lending, credit decision, adverse action",
            "banking-reg": "occ, fdic, federal reserve, dodd-frank, volcker, fiduciary, suitability, reg e, reg z, reg cc, cra",
            "fraud": "fraud, unauthorized, chargeback, identity theft, phishing, account takeover, wire transfer, suspicious transaction",
        }
    },
    "insurance": {
        "hint": "Insurance industry — claims processing, underwriting, actuarial, and regulatory compliance keywords.",
        "tier": "tier1", "classification": "confidential",
        "categories": {
            "claims": "claim, claimant, adjuster, settlement, liability, coverage, denial, subrogation, first notice of loss, reserve",
            "underwriting": "underwriting, risk assessment, premium, actuarial, loss ratio, combined ratio, reinsurance, catastrophe, exposure",
            "insurance-reg": "naic, state insurance, surplus lines, admitted, solvency, rate filing, market conduct, unfair claims practice",
            "policyholder": "policyholder, insured, beneficiary, endorsement, rider, exclusion, deductible, coinsurance, waiting period",
        }
    },
    "legal": {
        "hint": "Legal & law firm — case management, litigation, client privilege, and court terminology.",
        "tier": "tier1", "classification": "restricted",
        "categories": {
            "litigation": "lawsuit, plaintiff, defendant, motion, deposition, discovery, interrogatory, subpoena, summary judgment, verdict, appeal",
            "privilege": "attorney-client, work product, privileged, confidential communication, waiver, in camera, protective order",
            "contracts": "contract, agreement, clause, indemnification, liability, breach, damages, arbitration, mediation, force majeure",
            "court": "court, judge, magistrate, docket, filing, brief, exhibit, testimony, witness, jury, hearing, trial",
            "ethics-legal": "conflict of interest, malpractice, bar association, disciplinary, disqualification, pro bono, retainer",
        }
    },
    "realestate": {
        "hint": "Real estate — property transactions, fair housing, and regulatory compliance keywords.",
        "tier": "tier2", "classification": "confidential",
        "categories": {
            "transactions": "listing, closing, escrow, title, deed, mortgage, appraisal, inspection, contingency, earnest money, mls",
            "fair-housing": "fair housing, discrimination, protected class, reasonable accommodation, steering, blockbusting, redlining",
            "property": "zoning, permit, hoa, easement, lien, encumbrance, survey, plat, setback, variance, assessment",
            "leasing": "lease, tenant, landlord, eviction, security deposit, rent, occupancy, habitability, maintenance, renewal",
        }
    },
    "retail": {
        "hint": "Retail & e-commerce — customer data, payment processing, and consumer protection keywords.",
        "tier": "tier2", "classification": "confidential",
        "categories": {
            "payments": "payment, refund, chargeback, pci, credit card, transaction, checkout, gateway, recurring billing, authorization",
            "customer-data": "customer, order, shipping, returns, loyalty, account, preferences, cart, wishlist, review",
            "consumer-protection": "ftc, warranty, recall, false advertising, bait and switch, price gouging, terms of service, privacy policy",
            "inventory": "inventory, sku, fulfillment, warehouse, supply chain, vendor, procurement, demand forecast, stockout",
        }
    },
    "education": {
        "hint": "Education — FERPA student privacy, academic integrity, and institutional compliance keywords.",
        "tier": "tier2", "classification": "confidential",
        "categories": {
            "ferpa": "ferpa, student record, education record, directory information, consent, disclosure, eligible student, parent rights",
            "academic": "grade, transcript, enrollment, registration, curriculum, accreditation, assessment, learning outcome, syllabus",
            "integrity": "plagiarism, academic integrity, cheating, honor code, originality, citation, turnitin, ai detection, academic misconduct",
            "student-safety": "title ix, clery act, sexual harassment, discrimination, disability, accommodation, section 504, idea, iep",
        }
    },
    "government": {
        "hint": "Government & public sector — FOIA, public records, procurement, and security classification keywords.",
        "tier": "tier1", "classification": "restricted",
        "categories": {
            "records": "foia, public record, open records, redaction, exemption, classified, sensitive but unclassified, cui, fouo",
            "procurement": "rfp, rfq, bid, solicitation, contract, sole source, procurement, far, dfar, small business, set-aside",
            "security-gov": "clearance, nist, fisma, fedramp, stigs, ato, poam, vulnerability, incident, cve, stig",
            "compliance-gov": "ig, inspector general, gao, audit finding, corrective action, omb, circular, appropriation, anti-deficiency",
        }
    },
    "manufacturing": {
        "hint": "Manufacturing & supply chain — quality control, safety compliance, and logistics keywords.",
        "tier": "tier2", "classification": "internal",
        "categories": {
            "quality": "quality, defect, nonconformance, root cause, corrective action, capa, iso 9001, six sigma, spc, cpk, tolerance",
            "safety-mfg": "osha, lockout tagout, ppe, msds, sds, hazmat, incident, near miss, safety audit, ergonomic, workplace injury",
            "supply-chain": "supplier, vendor, procurement, lead time, bill of materials, mrp, erp, logistics, freight, customs, tariff",
            "production": "production, yield, throughput, downtime, maintenance, preventive, predictive, work order, changeover, lean",
        }
    },
    "custom": {
        "hint": "No preset keywords loaded. Add your own categories below.",
        "tier": "tier3", "classification": "internal", "categories": {}
    },
}


# =========================================================================
# Service functions
# =========================================================================

async def seed_templates_if_empty() -> dict:
    """Seed keyword templates into central DB if the table is empty."""
    def _check(db):
        result = db.execute(text(SQL.count_keyword_templates))
        return result.scalar()

    try:
        count = await run_central_query(_check)
    except Exception:
        return {"seeded": False, "message": "Central DB not available"}

    # Always re-seed (upsert) to fix any missing defaults like is_active
    if count and count > 0:
        logger.info(f"Re-seeding {count} existing templates (upsert)")

    def _seed(db):
        created = 0
        for industry, tmpl in SEED_TEMPLATES.items():
            db.execute(text(SQL.upsert_keyword_template), {
                "industry": industry,
                "hint": tmpl["hint"],
                "tier": tmpl["tier"],
                "classification": tmpl["classification"],
                "updated_by": "system-seed",
            })
            for idx, (cat, keywords) in enumerate(tmpl.get("categories", {}).items()):
                db.execute(text(SQL.upsert_keyword_category), {
                    "industry": industry,
                    "category": cat,
                    "keywords": keywords,
                    "sort_order": idx,
                })
            created += 1
        db.commit()
        return created

    try:
        created = await run_central_query(_seed)
        logger.info(f"Seeded {created} keyword templates")
        return {"seeded": True, "count": created}
    except Exception as e:
        logger.warning(f"Failed to seed keyword templates: {e}")
        return {"seeded": False, "message": str(e)}


async def list_templates() -> list[dict]:
    """List all active keyword templates with their categories."""
    def _query(db):
        result = db.execute(text(SQL.list_keyword_templates))
        # Fetch all rows first (pymssql doesn't support nested cursors)
        rows = [dict(row) for row in result.mappings()]
        templates = []
        for row in rows:
            cats = db.execute(text(SQL.get_keyword_categories), {"industry": row["industry"]})
            cat_rows = [dict(r) for r in cats.mappings()]
            templates.append({
                **row,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "categories": {r["category_name"]: r["keywords"] for r in cat_rows},
            })
        return templates

    result = await run_central_query(_query)
    return result if result else []


async def get_template(industry: str) -> dict | None:
    """Get a single industry template with its categories."""
    def _query(db):
        result = db.execute(text(SQL.get_keyword_template), {"industry": industry})
        row = result.mappings().first()
        if not row:
            return None
        cats = db.execute(text(SQL.get_keyword_categories), {"industry": industry})
        return {
            **dict(row),
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "categories": {r["category_name"]: r["keywords"] for r in cats.mappings()},
        }

    return await run_central_query(_query)


async def update_template(industry: str, hint: str, tier: str, classification: str,
                          categories: dict, updated_by: str) -> dict:
    """Update a template in the central DB. Called after change proposal is approved."""
    def _update(db):
        db.execute(text(SQL.upsert_keyword_template), {
            "industry": industry, "hint": hint, "tier": tier,
            "classification": classification, "updated_by": updated_by,
        })
        # Replace all categories
        db.execute(text(SQL.delete_keyword_categories), {"industry": industry})
        for idx, (cat, keywords) in enumerate(categories.items()):
            db.execute(text(SQL.upsert_keyword_category), {
                "industry": industry, "category": cat,
                "keywords": keywords, "sort_order": idx,
            })
        db.commit()
        return True

    await run_central_query(_update)
    return {"success": True, "industry": industry}
