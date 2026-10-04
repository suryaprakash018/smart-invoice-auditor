import os
import sys
import shutil
from typing import Optional, List
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.models import (
    VendorContract,
    ContractRate,
    ParsedInvoice,
    AuditReport,
    AuditStatus,
)
from src.database.session import get_db, init_db, engine
from src.database.models import (
    VendorRecord,
    ContractRecord,
    RateCardRecord,
    InvoiceRecord,
    InvoiceLineItemRecord,
    AuditRunRecord,
    AuditDiscrepancyRecord,
    HumanDecisionRecord,
)
from src.extractor import InvoiceExtractor
from src.audit_engine import ContractAuditEngine
from src.evals.evaluator import ComplianceEvaluator

# Initialize database schema on startup
init_db()

app = FastAPI(
    title="Veritas AP Compliance System",
    description="Enterprise Multi-modal Document Compliance & Human-in-the-Loop AP Auditor",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

SAMPLES_DIR = os.path.join(BASE_DIR, "data", "sample_invoices")
UPLOADS_DIR = os.path.join(BASE_DIR, "data", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Mount data folder for static PDF viewing
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "data")), name="static")

extractor = InvoiceExtractor()
engine_audit = ContractAuditEngine()


def _get_contract_pydantic_from_db(db: Session, vendor_name: str) -> Optional[VendorContract]:
    contract_rec = (
        db.query(ContractRecord)
        .join(VendorRecord)
        .filter(VendorRecord.name.ilike(f"%{vendor_name}%"))
        .first()
    )
    if not contract_rec:
        contract_rec = db.query(ContractRecord).first()

    if not contract_rec:
        return None

    return VendorContract(
        contract_id=contract_rec.contract_ref,
        vendor_name=contract_rec.vendor.name,
        effective_date=contract_rec.effective_date,
        expiry_date=contract_rec.expiry_date,
        payment_terms=contract_rec.payment_terms,
        rates=[
            ContractRate(
                role_or_item=r.role_or_service,
                agreed_rate=r.agreed_unit_rate,
                unit=r.unit,
                max_monthly_units=r.max_monthly_units,
            ) for r in contract_rec.rate_cards
        ],
        allowed_extra_fees=[],
        notes=contract_rec.raw_notes,
    )


def _persist_audit_to_db(db: Session, invoice: ParsedInvoice, report: AuditReport, pdf_path: Optional[str] = None):
    # Find or create vendor
    vendor = db.query(VendorRecord).filter(VendorRecord.name.ilike(f"%{invoice.vendor_name}%")).first()
    if not vendor:
        vendor = VendorRecord(name=invoice.vendor_name)
        db.add(vendor)
        db.flush()

    # Get contract
    contract = db.query(ContractRecord).filter(ContractRecord.vendor_id == vendor.id).first()
    if not contract:
        contract = db.query(ContractRecord).first()

    # Save invoice record
    inv_rec = InvoiceRecord(
        vendor_id=vendor.id,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        payment_terms=invoice.payment_terms,
        subtotal=invoice.subtotal,
        tax_amount=invoice.tax_amount,
        total_amount=invoice.total_amount,
        pdf_path=pdf_path,
    )
    db.add(inv_rec)
    db.flush()

    # Save line items
    for item in invoice.line_items:
        line_rec = InvoiceLineItemRecord(
            invoice_id=inv_rec.id,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            total_price=item.total_price,
        )
        db.add(line_rec)

    # Save audit run
    audit_rec = AuditRunRecord(
        invoice_id=inv_rec.id,
        contract_id=contract.id if contract else 1,
        status=report.status.value,
        total_billed=report.total_billed,
        total_expected=report.total_expected,
        total_overcharge=report.total_overcharge,
        dispute_draft=report.suggested_dispute_email,
    )
    db.add(audit_rec)
    db.flush()

    # Save discrepancies
    for d in report.discrepancies:
        disc_rec = AuditDiscrepancyRecord(
            audit_run_id=audit_rec.id,
            discrepancy_type=d.type.value,
            description=d.description,
            billed_amount=d.billed_amount,
            expected_amount=d.expected_amount,
            overcharge_amount=d.overcharge,
        )
        db.add(disc_rec)

    db.commit()
    return audit_rec.id


class HITLDecisionRequest(BaseModel):
    invoice_number: str
    vendor_name: str
    action: str  # "APPROVE_OVERCHARGE", "DISPUTE_AND_EMAIL", "REJECT"
    disputed_amount: float
    dispute_email_content: Optional[str] = None
    reviewer_notes: Optional[str] = None


@app.get("/api/contracts")
def list_contracts(db: Session = Depends(get_db)):
    contracts = db.query(ContractRecord).all()
    results = []
    for c in contracts:
        results.append({
            "contract_id": c.contract_ref,
            "vendor_name": c.vendor.name,
            "effective_date": c.effective_date,
            "expiry_date": c.expiry_date,
            "payment_terms": c.payment_terms,
            "rates": [
                {
                    "role_or_item": r.role_or_service,
                    "agreed_rate": r.agreed_unit_rate,
                    "unit": r.unit,
                    "max_monthly_units": r.max_monthly_units,
                } for r in c.rate_cards
            ]
        })
    return {"contracts": results}


@app.post("/api/audit-upload")
async def audit_uploaded_invoice(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF invoices are currently supported.")

    temp_path = os.path.join(UPLOADS_DIR, file.filename)
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        parsed_invoice = extractor.extract_from_pdf(temp_path)
        contract = _get_contract_pydantic_from_db(db, parsed_invoice.vendor_name)
        if not contract:
            raise HTTPException(status_code=404, detail="No matching contract found in database.")

        report = engine_audit.audit_invoice(parsed_invoice, contract)
        audit_id = _persist_audit_to_db(db, parsed_invoice, report, temp_path)

        return {
            "audit_id": audit_id,
            "invoice": parsed_invoice.model_dump(),
            "contract": contract.model_dump(),
            "report": report.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/audit-sample/{sample_type}")
def audit_sample_invoice(sample_type: str, db: Session = Depends(get_db)):
    filename = "invoice_valid.pdf" if sample_type == "valid" else "invoice_overcharged.pdf"
    pdf_path = os.path.join(SAMPLES_DIR, filename)

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Sample invoice not found.")

    parsed_invoice = extractor.extract_from_pdf(pdf_path)
    contract = _get_contract_pydantic_from_db(db, parsed_invoice.vendor_name)
    if not contract:
        raise HTTPException(status_code=404, detail="No matching contract found in database.")

    report = engine_audit.audit_invoice(parsed_invoice, contract)
    audit_id = _persist_audit_to_db(db, parsed_invoice, report, pdf_path)

    return {
        "audit_id": audit_id,
        "invoice": parsed_invoice.model_dump(),
        "contract": contract.model_dump(),
        "report": report.model_dump(),
    }


@app.post("/api/hitl-decision")
def record_hitl_decision(decision: HITLDecisionRequest, db: Session = Depends(get_db)):
    # Look up most recent audit run for invoice
    audit_run = (
        db.query(AuditRunRecord)
        .join(InvoiceRecord)
        .filter(InvoiceRecord.invoice_number == decision.invoice_number)
        .order_by(AuditRunRecord.id.desc())
        .first()
    )

    if decision.action == "DISPUTE_AND_EMAIL":
        status_message = (
            f"Formal dispute notice dispatched to {decision.vendor_name}. "
            f"Accounts Payable hold placed on invoice #{decision.invoice_number}. "
            f"Blocked Overcharge: ${decision.disputed_amount:,.2f}."
        )
    elif decision.action == "APPROVE_OVERCHARGE":
        status_message = (
            f"Manual exception granted by reviewer for #{decision.invoice_number}. "
            f"Invoice marked approved for payment with audit tag."
        )
    else:
        status_message = f"Invoice #{decision.invoice_number} rejected and returned to vendor."

    if audit_run:
        hitl_rec = HumanDecisionRecord(
            audit_run_id=audit_run.id,
            reviewer_id="Surya Prakash",
            action=decision.action,
            disputed_amount=decision.disputed_amount,
            reviewer_notes=decision.reviewer_notes or status_message,
        )
        db.add(hitl_rec)
        db.commit()

    # Calculate total blocked savings from database
    total_savings = (
        db.query(HumanDecisionRecord)
        .filter(HumanDecisionRecord.action.in_(["DISPUTE_AND_EMAIL", "REJECT"]))
        .with_entities(HumanDecisionRecord.disputed_amount)
        .all()
    )
    total_blocked = sum(s[0] for s in total_savings)

    return {
        "status": "SUCCESS",
        "message": status_message,
        "total_savings_to_date": total_blocked,
    }


@app.get("/api/metrics")
def get_metrics(db: Session = Depends(get_db)):
    total_audits = db.query(AuditRunRecord).count()
    flagged_audits = db.query(AuditRunRecord).filter(AuditRunRecord.status == "FLAGGED").count()
    
    total_savings = (
        db.query(HumanDecisionRecord)
        .filter(HumanDecisionRecord.action.in_(["DISPUTE_AND_EMAIL", "REJECT"]))
        .with_entities(HumanDecisionRecord.disputed_amount)
        .all()
    )
    total_blocked = sum(s[0] for s in total_savings)

    history = (
        db.query(HumanDecisionRecord)
        .order_by(HumanDecisionRecord.id.desc())
        .limit(20)
        .all()
    )

    return {
        "total_audits": total_audits,
        "flagged_audits": flagged_audits,
        "compliance_rate": round(((total_audits - flagged_audits) / max(1, total_audits)) * 100, 1),
        "total_savings_blocked": total_blocked,
        "history": [
            {
                "invoice_number": h.audit_run.invoice.invoice_number,
                "vendor_name": h.audit_run.invoice.vendor.name,
                "action": h.action,
                "disputed_amount": h.disputed_amount,
                "notes": h.reviewer_notes,
                "timestamp": h.decided_at.isoformat(),
            } for h in history
        ],
    }


@app.get("/api/evals/benchmark")
def get_evals_benchmark(db: Session = Depends(get_db)):
    contract = _get_contract_pydantic_from_db(db, "CloudScale Innovations")
    if not contract:
        raise HTTPException(status_code=404, detail="Default contract not found.")
    evaluator = ComplianceEvaluator(contract)
    results = evaluator.run_evaluations()
    return results


class CopilotChatRequest(BaseModel):
    message: str
    invoice_number: str
    vendor_name: str
    billed_total: float
    authorized_total: float
    current_overcharge: float
    discrepancies: List[str] = []


copilot_instance = None

def get_copilot():
    global copilot_instance
    if copilot_instance is None:
        from src.copilot import AuditCopilot
        copilot_instance = AuditCopilot()
    return copilot_instance


@app.post("/api/copilot/chat")
def copilot_chat(req: CopilotChatRequest, db: Session = Depends(get_db)):
    contract = _get_contract_pydantic_from_db(db, req.vendor_name)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found for vendor.")

    # Synthetic invoice and report representations for copilot context
    invoice = ParsedInvoice(
        vendor_name=req.vendor_name,
        invoice_number=req.invoice_number,
        line_items=[],
        subtotal=req.billed_total,
        total_amount=req.billed_total,
    )
    report = AuditReport(
        invoice_number=req.invoice_number,
        vendor_name=req.vendor_name,
        status=AuditStatus.FLAGGED if req.current_overcharge > 0 else AuditStatus.PASSED,
        total_billed=req.billed_total,
        total_expected=req.authorized_total,
        total_overcharge=req.current_overcharge,
        discrepancies=[],
    )

    copilot = get_copilot()
    result = copilot.chat(req.message, invoice, contract, report)
    return result


@app.get("/api/audit-certificate/{invoice_number}")
def download_audit_certificate(invoice_number: str, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    from src.certificate_generator import generate_audit_certificate

    cert_dir = os.path.join(BASE_DIR, "data", "certificates")
    os.makedirs(cert_dir, exist_ok=True)
    out_pdf = os.path.join(cert_dir, f"certificate_{invoice_number}.pdf")

    # Find audit record
    audit_rec = (
        db.query(AuditRunRecord)
        .join(InvoiceRecord)
        .filter(InvoiceRecord.invoice_number == invoice_number)
        .order_by(AuditRunRecord.id.desc())
        .first()
    )

    if not audit_rec:
        raise HTTPException(status_code=404, detail="Audit run not found for this invoice.")

    contract = _get_contract_pydantic_from_db(db, audit_rec.invoice.vendor.name)
    invoice = ParsedInvoice(
        vendor_name=audit_rec.invoice.vendor.name,
        invoice_number=audit_rec.invoice.invoice_number,
        invoice_date=audit_rec.invoice.invoice_date,
        due_date=audit_rec.invoice.due_date,
        payment_terms=audit_rec.invoice.payment_terms,
        line_items=[],
        subtotal=audit_rec.invoice.subtotal,
        total_amount=audit_rec.invoice.total_amount,
    )
    report = AuditReport(
        invoice_number=audit_rec.invoice.invoice_number,
        vendor_name=audit_rec.invoice.vendor.name,
        status=AuditStatus(audit_rec.status),
        total_billed=audit_rec.total_billed,
        total_expected=audit_rec.total_expected,
        total_overcharge=audit_rec.total_overcharge,
        discrepancies=[],
    )

    generate_audit_certificate(invoice, contract, report, out_pdf)
    return FileResponse(out_pdf, media_type="application/pdf", filename=f"Veritas_Audit_Certificate_{invoice_number}.pdf")


@app.post("/api/telegram/simulate")
def simulate_telegram():
    from src.telegram_bot import TelegramAuditBridge
    sample_pdf = os.path.join(BASE_DIR, "data", "sample_invoices", "invoice_overcharged.pdf")
    bridge = TelegramAuditBridge()
    return bridge.process_incoming_pdf(sample_pdf)


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    dashboard_file = os.path.join(BASE_DIR, "src", "dashboard.html")
    if os.path.exists(dashboard_file):
        with open(dashboard_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Veritas AP Compliance System</h1><p>dashboard.html not found</p>"
