"""
Veritas AP Enterprise - Vendor Reliability Index (VRI) & Behavioral Fraud Risk Matrix
Calculates longitudinal vendor trust scores (0-100), detects price-creep velocity,
and classifies suppliers into governance risk tiers.
"""

from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.database.models import (
    VendorRecord,
    ContractRecord,
    RateCardRecord,
    InvoiceRecord,
    AuditRunRecord,
    AuditDiscrepancyRecord,
    HumanDecisionRecord,
)


class RiskTier:
    TIER_1_LOW = "TIER_1_LOW"
    TIER_2_MODERATE = "TIER_2_MODERATE"
    TIER_3_ELEVATED = "TIER_3_ELEVATED"
    TIER_4_CRITICAL = "TIER_4_CRITICAL"


def compute_vri_score(
    pass_rate: float,
    leakage_rate: float,
    price_creep_velocity: float,
    unapproved_fee_count: int,
    rate_mismatch_count: int,
    active_disputes_count: int,
) -> float:
    """
    Computes deterministic Vendor Reliability Index (VRI) between 0.0 and 100.0.
    
    Formula:
    100 - (Fail Rate Penalty) - (Leakage Penalty) - (Creep Penalty) - (Fee Penalties) - (Dispute Penalties)
    """
    base_score = 100.0

    # 1. Audit Failure Rate Deduction (up to 25 points)
    fail_rate = max(0.0, 100.0 - pass_rate)
    fail_penalty = (fail_rate / 100.0) * 25.0

    # 2. Overcharge Leakage Ratio Deduction (up to 35 points)
    # leakage_rate is between 0.0 and 1.0 (e.g. 0.12 for 12% overcharge)
    leakage_penalty = min(35.0, leakage_rate * 250.0)

    # 3. Price Creep Velocity Deduction (up to 20 points)
    # If rates are creeping upward above contract (e.g. +18.75% -> 15.0 deduction)
    creep_penalty = min(20.0, max(0.0, price_creep_velocity * 0.8))

    # 4. Unauthorized Fees & Surcharges Penalty (10 points per occurrence, max 20)
    fee_penalty = min(20.0, unapproved_fee_count * 10.0)

    # 5. Rate Mismatch Frequency Penalty (5 points per occurrence, max 15)
    rate_penalty = min(15.0, rate_mismatch_count * 5.0)

    # 6. Active Unresolved Disputes Penalty (5 points per dispute, max 10)
    dispute_penalty = min(10.0, active_disputes_count * 5.0)

    total_deductions = (
        fail_penalty
        + leakage_penalty
        + creep_penalty
        + fee_penalty
        + rate_penalty
        + dispute_penalty
    )

    final_score = max(5.0, min(100.0, round(base_score - total_deductions, 1)))
    return final_score


def classify_risk_tier(vri_score: float) -> Dict[str, str]:
    """
    Maps VRI score to enterprise governance tiers and procurement recommendations.
    """
    if vri_score >= 90.0:
        return {
            "tier_code": RiskTier.TIER_1_LOW,
            "tier_name": "Tier 1: Low Risk (Trusted Partner)",
            "badge_color": "emerald",
            "governance_recommendation": "Eligible for Automated Straight-Through Processing (STP). No human sign-off required.",
            "action_code": "AUTO_APPROVE_ELIGIBLE",
        }
    elif vri_score >= 70.0:
        return {
            "tier_code": RiskTier.TIER_2_MODERATE,
            "tier_name": "Tier 2: Moderate Risk (Standard Monitoring)",
            "badge_color": "brand",
            "governance_recommendation": "Standard AP Reviewer verification. Sample 20% of itemized line items.",
            "action_code": "STANDARD_REVIEW",
        }
    elif vri_score >= 50.0:
        return {
            "tier_code": RiskTier.TIER_3_ELEVATED,
            "tier_name": "Tier 3: Elevated Risk (Procurement Watchlist)",
            "badge_color": "amber",
            "governance_recommendation": "Mandatory Dual Sign-off (AP Reviewer + Department Head). Strict line-by-line rate validation.",
            "action_code": "MANDATORY_DUAL_SIGNOFF",
        }
    else:
        return {
            "tier_code": RiskTier.TIER_4_CRITICAL,
            "tier_name": "Tier 4: Critical Risk (Forensic Hold)",
            "badge_color": "terracotta",
            "governance_recommendation": "Immediate Payment Hold. Mandatory Vice President authorization. Issue formal contract breach warning (§4.2).",
            "action_code": "FORENSIC_PAYMENT_HOLD",
        }


def calculate_vendor_risk_profile(db: Session, vendor_id: int) -> Optional[Dict[str, Any]]:
    """
    Computes comprehensive risk profile and longitudinal metrics for a specific vendor.
    """
    vendor = db.query(VendorRecord).filter(VendorRecord.id == vendor_id).first()
    if not vendor:
        return None

    contracts = db.query(ContractRecord).filter(ContractRecord.vendor_id == vendor.id).all()
    primary_contract = contracts[0] if contracts else None

    # Fetch all invoices for this vendor
    invoices = db.query(InvoiceRecord).filter(InvoiceRecord.vendor_id == vendor.id).all()
    invoice_ids = [inv.id for inv in invoices]

    if not invoices:
        # Default baseline for vendor with zero invoices yet audited
        vri_score = 95.0
        tier_info = classify_risk_tier(vri_score)
        return {
            "vendor_id": vendor.id,
            "vendor_name": vendor.name,
            "tax_identifier": vendor.tax_identifier or "N/A",
            "contact_email": vendor.contact_email or "N/A",
            "contract_ref": primary_contract.contract_ref if primary_contract else "NONE",
            "total_invoices_audited": 0,
            "passed_invoices": 0,
            "flagged_invoices": 0,
            "pass_rate": 100.0,
            "total_billed": 0.0,
            "total_expected": 0.0,
            "total_overcharge": 0.0,
            "leakage_rate_pct": 0.0,
            "price_creep_velocity_pct": 0.0,
            "unapproved_fee_count": 0,
            "rate_mismatch_count": 0,
            "payment_term_mismatch_count": 0,
            "active_disputes_count": 0,
            "vri_score": vri_score,
            "risk_tier": tier_info["tier_code"],
            "tier_name": tier_info["tier_name"],
            "badge_color": tier_info["badge_color"],
            "governance_recommendation": tier_info["governance_recommendation"],
            "action_code": tier_info["action_code"],
            "stp_eligible": True,
            "risk_factors": {
                "rate_integrity": 100.0,
                "clause_adherence": 100.0,
                "billing_accuracy": 100.0,
                "dispute_friction": 100.0,
            },
            "recent_audits": [],
        }

    # Fetch audit runs for these invoices
    audit_runs = (
        db.query(AuditRunRecord)
        .filter(AuditRunRecord.invoice_id.in_(invoice_ids))
        .all()
    )
    audit_ids = [ar.id for ar in audit_runs]

    total_invoices = len(invoices)
    passed_count = sum(1 for ar in audit_runs if ar.status == "PASSED")
    flagged_count = sum(1 for ar in audit_runs if ar.status in ["FLAGGED", "REJECTED"])
    pass_rate = round((passed_count / total_invoices) * 100.0, 1) if total_invoices > 0 else 100.0

    total_billed = sum(inv.total_amount for inv in invoices)
    total_overcharge = sum(ar.total_overcharge for ar in audit_runs)
    total_expected = max(0.0, total_billed - total_overcharge)

    leakage_ratio = (total_overcharge / total_billed) if total_billed > 0 else 0.0
    leakage_rate_pct = round(leakage_ratio * 100.0, 2)

    # Discrepancy breakdown
    discrepancies = (
        db.query(AuditDiscrepancyRecord)
        .filter(AuditDiscrepancyRecord.audit_run_id.in_(audit_ids))
        .all()
        if audit_ids else []
    )

    unapproved_fee_count = sum(1 for d in discrepancies if d.discrepancy_type == "UNAPPROVED_FEE")
    rate_mismatch_count = sum(1 for d in discrepancies if d.discrepancy_type == "RATE_MISMATCH")
    payment_term_mismatch_count = sum(1 for d in discrepancies if d.discrepancy_type == "PAYMENT_TERM_MISMATCH")

    # Active disputes count
    decisions = (
        db.query(HumanDecisionRecord)
        .filter(HumanDecisionRecord.audit_run_id.in_(audit_ids))
        .all()
        if audit_ids else []
    )
    active_disputes_count = sum(1 for dec in decisions if dec.action in ["DISPUTE_AND_EMAIL", "CONDITIONAL_HOLD"])

    # Price Creep Velocity calculation:
    # Measure max percentage difference between billed hourly rate and agreed contract rate
    max_rate_creep_pct = 0.0
    if primary_contract and primary_contract.rate_cards:
        contract_rates = {rc.role_or_service.lower(): rc.agreed_unit_rate for rc in primary_contract.rate_cards}
        for inv in invoices:
            for item in inv.line_items:
                desc_lower = item.description.lower()
                for role_title, agreed_rate in contract_rates.items():
                    if role_title in desc_lower or any(word in desc_lower for word in role_title.split()[:2]):
                        if item.unit_price > agreed_rate:
                            pct_diff = ((item.unit_price - agreed_rate) / agreed_rate) * 100.0
                            if pct_diff > max_rate_creep_pct:
                                max_rate_creep_pct = pct_diff

    # If CloudScale Innovations billed $95/hr vs $80/hr contracted, that's +18.75% creep!
    price_creep_velocity_pct = round(max_rate_creep_pct, 1)

    # Compute VRI
    vri_score = compute_vri_score(
        pass_rate=pass_rate,
        leakage_rate=leakage_ratio,
        price_creep_velocity=price_creep_velocity_pct,
        unapproved_fee_count=unapproved_fee_count,
        rate_mismatch_count=rate_mismatch_count,
        active_disputes_count=active_disputes_count,
    )

    tier_info = classify_risk_tier(vri_score)

    # Risk factor sub-scores (0-100)
    rate_integrity = max(10.0, round(100.0 - (rate_mismatch_count * 15.0) - (price_creep_velocity_pct * 1.2), 1))
    clause_adherence = max(10.0, round(100.0 - (unapproved_fee_count * 25.0) - (payment_term_mismatch_count * 10.0), 1))
    billing_accuracy = max(10.0, round(100.0 - (leakage_rate_pct * 3.5), 1))
    dispute_friction = max(10.0, round(100.0 - (active_disputes_count * 20.0), 1))

    recent_audits = []
    for ar in sorted(audit_runs, key=lambda x: x.audited_at, reverse=True)[:5]:
        inv = ar.invoice
        recent_audits.append({
            "invoice_number": inv.invoice_number if inv else "N/A",
            "audited_at": ar.audited_at.strftime("%Y-%m-%d %H:%M") if ar.audited_at else "",
            "status": ar.status,
            "total_billed": ar.total_billed,
            "total_overcharge": ar.total_overcharge,
        })

    return {
        "vendor_id": vendor.id,
        "vendor_name": vendor.name,
        "tax_identifier": vendor.tax_identifier or "N/A",
        "contact_email": vendor.contact_email or "N/A",
        "contract_ref": primary_contract.contract_ref if primary_contract else "NONE",
        "payment_terms": primary_contract.payment_terms if primary_contract else "Net 30",
        "total_invoices_audited": total_invoices,
        "passed_invoices": passed_count,
        "flagged_invoices": flagged_count,
        "pass_rate": pass_rate,
        "total_billed": round(total_billed, 2),
        "total_expected": round(total_expected, 2),
        "total_overcharge": round(total_overcharge, 2),
        "leakage_rate_pct": leakage_rate_pct,
        "price_creep_velocity_pct": price_creep_velocity_pct,
        "unapproved_fee_count": unapproved_fee_count,
        "rate_mismatch_count": rate_mismatch_count,
        "payment_term_mismatch_count": payment_term_mismatch_count,
        "active_disputes_count": active_disputes_count,
        "vri_score": vri_score,
        "risk_tier": tier_info["tier_code"],
        "tier_name": tier_info["tier_name"],
        "badge_color": tier_info["badge_color"],
        "governance_recommendation": tier_info["governance_recommendation"],
        "action_code": tier_info["action_code"],
        "stp_eligible": (vri_score >= 90.0),
        "risk_factors": {
            "rate_integrity": rate_integrity,
            "clause_adherence": clause_adherence,
            "billing_accuracy": billing_accuracy,
            "dispute_friction": dispute_friction,
        },
        "recent_audits": recent_audits,
    }


def get_fleet_vendor_risk_matrix(db: Session) -> Dict[str, Any]:
    """
    Computes company-wide supplier risk intelligence across all active vendors.
    """
    vendors = db.query(VendorRecord).order_by(VendorRecord.id.asc()).all()
    vendor_profiles = []

    for v in vendors:
        profile = calculate_vendor_risk_profile(db, v.id)
        if profile:
            vendor_profiles.append(profile)

    total_vendors = len(vendor_profiles)
    if total_vendors == 0:
        return {
            "kpis": {
                "fleet_average_vri": 100.0,
                "total_vendors": 0,
                "high_risk_vendors_count": 0,
                "stp_eligible_count": 0,
                "stp_eligibility_pct": 100.0,
                "total_capital_at_risk": 0.0,
            },
            "vendors": [],
        }

    fleet_average_vri = round(sum(p["vri_score"] for p in vendor_profiles) / total_vendors, 1)
    high_risk_count = sum(1 for p in vendor_profiles if p["risk_tier"] in [RiskTier.TIER_3_ELEVATED, RiskTier.TIER_4_CRITICAL])
    stp_count = sum(1 for p in vendor_profiles if p["stp_eligible"])
    stp_pct = round((stp_count / total_vendors) * 100.0, 1)
    total_capital_at_risk = round(sum(p["total_overcharge"] for p in vendor_profiles), 2)

    # Sort vendors by risk severity (lowest VRI / highest risk first)
    sorted_vendors = sorted(vendor_profiles, key=lambda x: x["vri_score"])

    return {
        "kpis": {
            "fleet_average_vri": fleet_average_vri,
            "total_vendors": total_vendors,
            "high_risk_vendors_count": high_risk_count,
            "stp_eligible_count": stp_count,
            "stp_eligibility_pct": stp_pct,
            "total_capital_at_risk": total_capital_at_risk,
        },
        "vendors": sorted_vendors,
    }
