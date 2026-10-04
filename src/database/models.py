import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Enum as SqlEnum,
)
from sqlalchemy.orm import relationship

from src.database.session import Base
from src.models import DiscrepancyType, AuditStatus


class VendorRecord(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    tax_identifier = Column(String(64), nullable=True)
    contact_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    contracts = relationship("ContractRecord", back_populates="vendor", cascade="all, delete-orphan")
    invoices = relationship("InvoiceRecord", back_populates="vendor", cascade="all, delete-orphan")


class ContractRecord(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    contract_ref = Column(String(128), unique=True, index=True, nullable=False)
    effective_date = Column(String(32), nullable=False)
    expiry_date = Column(String(32), nullable=False)
    payment_terms = Column(String(64), default="Net 30", nullable=False)
    raw_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    vendor = relationship("VendorRecord", back_populates="contracts")
    rate_cards = relationship("RateCardRecord", back_populates="contract", cascade="all, delete-orphan")
    audit_runs = relationship("AuditRunRecord", back_populates="contract")


class RateCardRecord(Base):
    __tablename__ = "rate_cards"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    role_or_service = Column(String(255), nullable=False)
    agreed_unit_rate = Column(Float, nullable=False)
    unit = Column(String(32), default="hour", nullable=False)
    max_monthly_units = Column(Float, nullable=True)

    contract = relationship("ContractRecord", back_populates="rate_cards")


class InvoiceRecord(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)
    invoice_number = Column(String(128), index=True, nullable=False)
    invoice_date = Column(String(32), nullable=True)
    due_date = Column(String(32), nullable=True)
    payment_terms = Column(String(64), nullable=True)
    currency = Column(String(16), default="USD")
    subtotal = Column(Float, nullable=False)
    tax_amount = Column(Float, default=0.0)
    total_amount = Column(Float, nullable=False)
    pdf_path = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    vendor = relationship("VendorRecord", back_populates="invoices")
    line_items = relationship("InvoiceLineItemRecord", back_populates="invoice", cascade="all, delete-orphan")
    audit_runs = relationship("AuditRunRecord", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLineItemRecord(Base):
    __tablename__ = "invoice_line_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    description = Column(String(512), nullable=False)
    quantity = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    invoice = relationship("InvoiceRecord", back_populates="line_items")


class AuditRunRecord(Base):
    __tablename__ = "audit_runs"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    status = Column(String(32), nullable=False)  # PASSED, FLAGGED, REJECTED
    total_billed = Column(Float, nullable=False)
    total_expected = Column(Float, nullable=False)
    total_overcharge = Column(Float, nullable=False)
    dispute_draft = Column(Text, nullable=True)
    audited_at = Column(DateTime, default=datetime.datetime.utcnow)

    invoice = relationship("InvoiceRecord", back_populates="audit_runs")
    contract = relationship("ContractRecord", back_populates="audit_runs")
    discrepancies = relationship("AuditDiscrepancyRecord", back_populates="audit_run", cascade="all, delete-orphan")
    human_decisions = relationship("HumanDecisionRecord", back_populates="audit_run", cascade="all, delete-orphan")


class AuditDiscrepancyRecord(Base):
    __tablename__ = "audit_discrepancies"

    id = Column(Integer, primary_key=True, index=True)
    audit_run_id = Column(Integer, ForeignKey("audit_runs.id"), nullable=False)
    discrepancy_type = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    billed_amount = Column(Float, default=0.0)
    expected_amount = Column(Float, default=0.0)
    overcharge_amount = Column(Float, default=0.0)

    audit_run = relationship("AuditRunRecord", back_populates="discrepancies")


class HumanDecisionRecord(Base):
    __tablename__ = "human_decisions"

    id = Column(Integer, primary_key=True, index=True)
    audit_run_id = Column(Integer, ForeignKey("audit_runs.id"), nullable=False)
    reviewer_id = Column(String(128), default="Surya Prakash", nullable=False)
    action = Column(String(64), nullable=False)  # APPROVE_OVERCHARGE, DISPUTE_AND_EMAIL, REJECT
    disputed_amount = Column(Float, default=0.0)
    reviewer_notes = Column(Text, nullable=True)
    decided_at = Column(DateTime, default=datetime.datetime.utcnow)

    audit_run = relationship("AuditRunRecord", back_populates="human_decisions")
