import pytest
from src.models import (
    ParsedInvoice,
    InvoiceLineItem,
    VendorContract,
    ContractRate,
    AuditStatus,
    DiscrepancyType,
)
from src.audit_engine import ContractAuditEngine


@pytest.fixture
def sample_contract():
    return VendorContract(
        contract_id="MSA-TEST-01",
        vendor_name="Test Vendor Inc",
        effective_date="2025-01-01",
        expiry_date="2026-12-31",
        payment_terms="Net 30",
        rates=[
            ContractRate(role_or_item="Senior DevOps Engineer", agreed_rate=80.0, max_monthly_units=160.0),
            ContractRate(role_or_item="QA Engineer", agreed_rate=50.0, max_monthly_units=160.0),
        ],
        allowed_extra_fees=["Approved Pre-flight Travel"],
    )


def test_compliant_invoice_passes(sample_contract):
    engine = ContractAuditEngine()
    invoice = ParsedInvoice(
        vendor_name="Test Vendor Inc",
        invoice_number="INV-001",
        payment_terms="Net 30",
        line_items=[InvoiceLineItem(description="Senior DevOps Engineer", quantity=80, unit_price=80, total_price=6400)],
        subtotal=6400, tax_amount=0, total_amount=6400,
    )
    report = engine.audit_invoice(invoice, sample_contract)
    assert report.status == AuditStatus.PASSED
    assert report.total_overcharge == 0.0
    assert len(report.discrepancies) == 0
    assert report.suggested_dispute_email is None


def test_rate_mismatch_detected(sample_contract):
    engine = ContractAuditEngine()
    invoice = ParsedInvoice(
        vendor_name="Test Vendor Inc",
        invoice_number="INV-002",
        payment_terms="Net 30",
        line_items=[InvoiceLineItem(description="Senior DevOps Engineer", quantity=80, unit_price=95, total_price=7600)],
        subtotal=7600, tax_amount=0, total_amount=7600,
    )
    report = engine.audit_invoice(invoice, sample_contract)
    assert report.status == AuditStatus.FLAGGED
    assert report.total_overcharge == 1200.0  # (95 - 80) * 80
    assert any(d.type == DiscrepancyType.RATE_MISMATCH for d in report.discrepancies)
    assert report.suggested_dispute_email is not None


def test_unapproved_fee_flagged(sample_contract):
    engine = ContractAuditEngine()
    invoice = ParsedInvoice(
        vendor_name="Test Vendor Inc",
        invoice_number="INV-003",
        payment_terms="Net 30",
        line_items=[
            InvoiceLineItem(description="Senior DevOps Engineer", quantity=40, unit_price=80, total_price=3200),
            InvoiceLineItem(description="Unapproved Platform License Fee", quantity=1, unit_price=450, total_price=450),
        ],
        subtotal=3650, tax_amount=0, total_amount=3650,
    )
    report = engine.audit_invoice(invoice, sample_contract)
    assert report.status == AuditStatus.FLAGGED
    assert report.total_overcharge == 450.0
    assert any(d.type == DiscrepancyType.UNAPPROVED_FEE for d in report.discrepancies)


def test_hour_cap_exceeded(sample_contract):
    engine = ContractAuditEngine()
    invoice = ParsedInvoice(
        vendor_name="Test Vendor Inc",
        invoice_number="INV-004",
        payment_terms="Net 30",
        line_items=[InvoiceLineItem(description="Senior DevOps Engineer", quantity=180, unit_price=80, total_price=14400)],
        subtotal=14400, tax_amount=0, total_amount=14400,
    )
    report = engine.audit_invoice(invoice, sample_contract)
    assert report.status == AuditStatus.FLAGGED
    assert report.total_overcharge == 1600.0  # 20 excess hours * $80
    assert any(d.type == DiscrepancyType.HOURS_EXCEEDED for d in report.discrepancies)


def test_payment_term_mismatch(sample_contract):
    engine = ContractAuditEngine()
    invoice = ParsedInvoice(
        vendor_name="Test Vendor Inc",
        invoice_number="INV-005",
        payment_terms="Net 15",  # Contract says Net 30!
        line_items=[InvoiceLineItem(description="Senior DevOps Engineer", quantity=40, unit_price=80, total_price=3200)],
        subtotal=3200, tax_amount=0, total_amount=3200,
    )
    report = engine.audit_invoice(invoice, sample_contract)
    assert report.status == AuditStatus.FLAGGED
    assert any(d.type == DiscrepancyType.PAYMENT_TERM_MISMATCH for d in report.discrepancies)
