import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.database.session import engine, init_db, SessionLocal
from src.database.models import (
    VendorRecord,
    ContractRecord,
    RateCardRecord,
    InvoiceRecord,
    InvoiceLineItemRecord,
    AuditRunRecord,
)


def seed_database():
    init_db()
    db = SessionLocal()

    try:
        print("[INFO] Initializing Master Service Agreements & Supplier Risk Fleet...")

        # 1. CloudScale Innovations (Tier 3/4 Elevated Watchlist)
        vendor_cs = db.query(VendorRecord).filter_by(name="CloudScale Innovations").first()
        if not vendor_cs:
            vendor_cs = VendorRecord(
                name="CloudScale Innovations",
                tax_identifier="US-EIN-884920194",
                contact_email="billing@cloudscale.io",
            )
            db.add(vendor_cs)
            db.flush()

            contract_cs = ContractRecord(
                vendor_id=vendor_cs.id,
                contract_ref="MSA-2025-CS01",
                effective_date="2025-01-01",
                expiry_date="2026-12-31",
                payment_terms="Net 30",
                raw_notes="Section 4.2: Any overtime, off-hours platform surcharges, or travel fees must be approved in writing via an authorized Change Order prior to billing.",
            )
            db.add(contract_cs)
            db.flush()

            rate_cards_cs = [
                RateCardRecord(
                    contract_id=contract_cs.id,
                    role_or_service="Senior DevOps Engineer",
                    agreed_unit_rate=80.0,
                    unit="hour",
                    max_monthly_units=160.0,
                ),
                RateCardRecord(
                    contract_id=contract_cs.id,
                    role_or_service="QA Automation Engineer",
                    agreed_unit_rate=55.0,
                    unit="hour",
                    max_monthly_units=160.0,
                ),
                RateCardRecord(
                    contract_id=contract_cs.id,
                    role_or_service="Cloud Solutions Architect",
                    agreed_unit_rate=120.0,
                    unit="hour",
                    max_monthly_units=80.0,
                ),
            ]
            db.add_all(rate_cards_cs)
            db.flush()

        # 2. Nexus Data Systems (Tier 2 Moderate Risk)
        vendor_nx = db.query(VendorRecord).filter_by(name="Nexus Data Systems").first()
        if not vendor_nx:
            vendor_nx = VendorRecord(
                name="Nexus Data Systems",
                tax_identifier="US-EIN-993817264",
                contact_email="ap@nexusdata.tech",
            )
            db.add(vendor_nx)
            db.flush()

            contract_nx = ContractRecord(
                vendor_id=vendor_nx.id,
                contract_ref="MSA-2024-NX09",
                effective_date="2024-06-01",
                expiry_date="2025-06-01",
                payment_terms="Net 45",
                raw_notes="Fixed-fee rates. No unapproved travel or hardware surcharges permitted.",
            )
            db.add(contract_nx)
            db.flush()

            rate_cards_nx = [
                RateCardRecord(
                    contract_id=contract_nx.id,
                    role_or_service="Staff Data Engineer",
                    agreed_unit_rate=130.0,
                    unit="hour",
                    max_monthly_units=120.0,
                ),
                RateCardRecord(
                    contract_id=contract_nx.id,
                    role_or_service="MLOps Infrastructure Consultant",
                    agreed_unit_rate=145.0,
                    unit="hour",
                    max_monthly_units=100.0,
                ),
            ]
            db.add_all(rate_cards_nx)
            db.flush()

        # Baseline invoice for Nexus Data Systems
        if vendor_nx:
            existing_nx_inv = db.query(InvoiceRecord).filter_by(vendor_id=vendor_nx.id).first()
            if not existing_nx_inv:
                contract_nx = db.query(ContractRecord).filter_by(vendor_id=vendor_nx.id).first()
                inv_nx_1 = InvoiceRecord(
                    vendor_id=vendor_nx.id,
                    invoice_number="INV-2025-NX01",
                    invoice_date="2025-02-10",
                    due_date="2025-03-27",
                    payment_terms="Net 45",
                    subtotal=10400.0,
                    tax_amount=0.0,
                    total_amount=10400.0,
                )
                db.add(inv_nx_1)
                db.flush()
                db.add(InvoiceLineItemRecord(
                    invoice_id=inv_nx_1.id,
                    description="Staff Data Engineer",
                    quantity=80.0,
                    unit_price=130.0,
                    total_price=10400.0,
                ))
                db.flush()
                db.add(AuditRunRecord(
                    invoice_id=inv_nx_1.id,
                    contract_id=contract_nx.id if contract_nx else 1,
                    status="PASSED",
                    total_billed=10400.0,
                    total_expected=10400.0,
                    total_overcharge=0.0,
                    dispute_draft=None,
                ))
                db.flush()

        # 3. Apex Cyber Defense (Tier 1 Trusted Partner / STP Eligible)
        vendor_apex = db.query(VendorRecord).filter_by(name="Apex Cyber Defense").first()
        if not vendor_apex:
            vendor_apex = VendorRecord(
                name="Apex Cyber Defense",
                tax_identifier="US-EIN-772910384",
                contact_email="billing@apexdefense.sec",
            )
            db.add(vendor_apex)
            db.flush()

            contract_apex = ContractRecord(
                vendor_id=vendor_apex.id,
                contract_ref="MSA-2025-AP03",
                effective_date="2025-01-01",
                expiry_date="2026-12-31",
                payment_terms="Net 30",
                raw_notes="Strict adherence to cybersecurity labor schedule. Clean historical compliance.",
            )
            db.add(contract_apex)
            db.flush()

            rate_cards_apex = [
                RateCardRecord(
                    contract_id=contract_apex.id,
                    role_or_service="Principal Security Architect",
                    agreed_unit_rate=160.0,
                    unit="hour",
                    max_monthly_units=100.0,
                ),
                RateCardRecord(
                    contract_id=contract_apex.id,
                    role_or_service="SOC Incident Responder",
                    agreed_unit_rate=90.0,
                    unit="hour",
                    max_monthly_units=160.0,
                ),
            ]
            db.add_all(rate_cards_apex)
            db.flush()

            # Seed clean historical invoices for Apex Cyber Defense
            inv_apex_1 = InvoiceRecord(
                vendor_id=vendor_apex.id,
                invoice_number="INV-2025-AP01",
                invoice_date="2025-01-31",
                due_date="2025-03-02",
                payment_terms="Net 30",
                subtotal=13600.0,
                tax_amount=0.0,
                total_amount=13600.0,
            )
            db.add(inv_apex_1)
            db.flush()

            db.add(InvoiceLineItemRecord(
                invoice_id=inv_apex_1.id,
                description="Principal Security Architect",
                quantity=40.0,
                unit_price=160.0,
                total_price=6400.0,
            ))
            db.add(InvoiceLineItemRecord(
                invoice_id=inv_apex_1.id,
                description="SOC Incident Responder",
                quantity=80.0,
                unit_price=90.0,
                total_price=7200.0,
            ))
            db.flush()

            db.add(AuditRunRecord(
                invoice_id=inv_apex_1.id,
                contract_id=contract_apex.id,
                status="PASSED",
                total_billed=13600.0,
                total_expected=13600.0,
                total_overcharge=0.0,
                dispute_draft=None,
            ))
            db.flush()

        db.commit()
        print("[SUCCESS] Supplier Risk Fleet initialized with 3 enterprise vendors and historical audit baselines.")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to seed database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
