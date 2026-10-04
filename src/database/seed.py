import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.database.session import engine, init_db, SessionLocal
from src.database.models import VendorRecord, ContractRecord, RateCardRecord


def seed_database():
    init_db()
    db = SessionLocal()

    try:
        # Check if already seeded
        existing = db.query(VendorRecord).filter_by(name="CloudScale Innovations").first()
        if existing:
            print("[INFO] Database already initialized and seeded.")
            return

        print("[INFO] Seeding Master Service Agreements into relational database...")

        # 1. CloudScale Innovations
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

        # 2. Nexus Data Systems
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

        db.commit()
        print("[SUCCESS] Database seeded with active vendor contracts and rate cards.")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to seed database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
