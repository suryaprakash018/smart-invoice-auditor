from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class DiscrepancyType(str, Enum):
    RATE_MISMATCH = "RATE_MISMATCH"
    UNAPPROVED_FEE = "UNAPPROVED_FEE"
    HOURS_EXCEEDED = "HOURS_EXCEEDED"
    MATH_CALCULATION_ERROR = "MATH_CALCULATION_ERROR"
    PAYMENT_TERM_MISMATCH = "PAYMENT_TERM_MISMATCH"


class AuditStatus(str, Enum):
    PASSED = "PASSED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


class InvoiceLineItem(BaseModel):
    description: str = Field(description="Description of the service or product billed")
    quantity: float = Field(description="Number of hours, units, or items billed")
    unit_price: float = Field(description="Price per unit or hourly rate billed")
    total_price: float = Field(description="Total price for this line item")


class ParsedInvoice(BaseModel):
    vendor_name: str = Field(description="Name of the vendor or contractor issuing the invoice")
    invoice_number: str = Field(description="Unique invoice identifier/code")
    invoice_date: Optional[str] = Field(default=None, description="Date the invoice was issued (YYYY-MM-DD)")
    due_date: Optional[str] = Field(default=None, description="Payment due date")
    payment_terms: Optional[str] = Field(default=None, description="Stated payment terms, e.g., Net 30, Due upon receipt")
    currency: str = Field(default="USD", description="Currency symbol or 3-letter code")
    line_items: List[InvoiceLineItem] = Field(default_factory=list, description="Extracted line items")
    subtotal: float = Field(description="Subtotal before taxes or discounts")
    tax_amount: float = Field(default=0.0, description="Tax or VAT billed")
    total_amount: float = Field(description="Final total billed amount")
    document_type: str = Field(default="PDF_VECTOR", description="Document ingestion type: PDF_VECTOR, IMAGE_OCR, or SCANNED_PDF")


class ContractRate(BaseModel):
    role_or_item: str = Field(description="Role title or service item (e.g. Senior DevOps Engineer)")
    agreed_rate: float = Field(description="Agreed contractual hourly rate or unit price")
    unit: str = Field(default="hour", description="Unit of charge, e.g., hour, month, license")
    max_monthly_units: Optional[float] = Field(default=None, description="Maximum billable units per month before requiring approval")


class VendorContract(BaseModel):
    contract_id: str = Field(description="Unique contract or MSA reference number")
    vendor_name: str = Field(description="Official name of the vendor")
    effective_date: str = Field(description="Contract start date (YYYY-MM-DD)")
    expiry_date: str = Field(description="Contract expiration date (YYYY-MM-DD)")
    payment_terms: str = Field(default="Net 30", description="Contracted payment terms")
    rates: List[ContractRate] = Field(default_factory=list, description="Approved rate cards")
    allowed_extra_fees: List[str] = Field(default_factory=list, description="Explicitly permitted surcharges/fees")
    notes: Optional[str] = Field(default=None, description="Additional legal or operational notes")


class DiscrepancyItem(BaseModel):
    type: DiscrepancyType = Field(description="Category of the detected issue")
    description: str = Field(description="Detailed explanation of the discrepancy")
    billed_amount: float = Field(description="What the vendor billed")
    expected_amount: float = Field(description="What was allowed according to the contract")
    overcharge: float = Field(description="Difference (billed - expected)")


class AuditReport(BaseModel):
    invoice_number: str
    vendor_name: str
    status: AuditStatus
    total_billed: float
    total_expected: float
    total_overcharge: float
    discrepancies: List[DiscrepancyItem] = Field(default_factory=list)
    suggested_dispute_email: Optional[str] = Field(
        default=None, description="Drafted dispute email if status is FLAGGED"
    )
