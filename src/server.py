import os
import sys
import shutil
import uuid
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, BackgroundTasks, Header
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.models import (
    VendorContract,
    ContractRate,
    ParsedInvoice,
    InvoiceLineItem,
    DiscrepancyItem,
    DiscrepancyType,
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
    UserRecord,
    ERPExportRecord,
    WebhookEventRecord,
)
from src.integrations.erp_exporter import generate_erp_export
from src.integrations.webhook_dispatcher import dispatch_webhook
from src.intelligence.vendor_risk_matrix import (
    get_fleet_vendor_risk_matrix,
    calculate_vendor_risk_profile,
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
    action: str  # "APPROVE_OVERCHARGE", "DISPUTE_AND_EMAIL", "REJECT", "PARTIAL_APPROVE", "CONDITIONAL_DISPUTE", "ROUTE_WORKFLOW"
    disputed_amount: float
    partial_approved_amount: Optional[float] = None
    routing_target: Optional[str] = None  # e.g., "LEGAL", "PROCUREMENT", "VP_FINANCE"
    dispute_email_content: Optional[str] = None
    reviewer_notes: Optional[str] = None
    reviewer_id: Optional[str] = "Surya Prakash"
    reviewer_role: Optional[str] = "AP_REVIEWER"


class ERPExportRequest(BaseModel):
    invoice_number: str
    erp_system: str = "SAP"  # "SAP", "NETSUITE", "QUICKBOOKS"
    format: str = "csv"  # "csv", "json"
    reviewer_id: Optional[str] = "Surya Prakash"


class WebhookDispatchRequest(BaseModel):
    event_type: str = "invoice.audit.flagged"
    invoice_number: str
    target_url: Optional[str] = None
    simulate: bool = True


@app.get("/api/auth/users")
def list_users(db: Session = Depends(get_db)):
    users = db.query(UserRecord).order_by(UserRecord.id.asc()).all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "role": u.role,
                "title": u.title,
                "avatar_color": u.avatar_color,
            }
            for u in users
        ]
    }


@app.get("/api/auth/me")
def get_current_user_profile(
    x_user_username: Optional[str] = Header(None, alias="X-User-Username"),
    username: Optional[str] = None,
    db: Session = Depends(get_db),
):
    target_username = username or x_user_username or "surya.prakash"
    user = db.query(UserRecord).filter(UserRecord.username == target_username).first()
    if not user:
        user = db.query(UserRecord).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    is_vp = (user.role == "FINANCE_VP")
    is_readonly = (user.role == "AUDITOR_READONLY")

    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "title": user.title,
        "avatar_color": user.avatar_color,
        "permissions": {
            "can_audit": True,
            "can_dispute": not is_readonly,
            "can_partial_remit": not is_readonly,
            "can_conditional_hold": not is_readonly,
            "can_route_workflow": not is_readonly,
            "can_approve_override": is_vp,
            "is_readonly": is_readonly,
        },
    }


# In-Memory Task Queue for Batch Processing
batch_tasks: Dict[str, Dict[str, Any]] = {}


def _process_batch_task(batch_id: str, file_paths: List[str]):
    from src.database.session import SessionLocal
    db = SessionLocal()
    task = batch_tasks.get(batch_id)
    if not task:
        db.close()
        return

    task["status"] = "PROCESSING"
    results = []

    try:
        for idx, path in enumerate(file_paths):
            try:
                parsed_inv = extractor.extract_from_pdf(path)
                contract = _get_contract_pydantic_from_db(db, parsed_inv.vendor_name)
                report = engine_audit.audit_invoice(parsed_inv, contract)
                audit_id = _persist_audit_to_db(db, parsed_inv, report, path)
                results.append({
                    "filename": os.path.basename(path),
                    "status": "SUCCESS",
                    "audit_id": audit_id,
                    "invoice_number": parsed_inv.invoice_number,
                    "compliance_status": report.status.value,
                    "total_overcharge": report.total_overcharge,
                })
            except Exception as item_err:
                results.append({
                    "filename": os.path.basename(path),
                    "status": "ERROR",
                    "error": str(item_err),
                })
            task["completed_files"] = idx + 1
            task["progress_percent"] = int(((idx + 1) / task["total_files"]) * 100)

        task["status"] = "COMPLETED"
        task["results"] = results
    except Exception as batch_err:
        task["status"] = "FAILED"
        task["error"] = str(batch_err)
    finally:
        db.close()


@app.post("/api/audit-batch")
async def audit_batch_invoices(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded for batch processing.")

    batch_id = str(uuid.uuid4())[:8]
    saved_paths = []

    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            continue
        save_path = os.path.join(UPLOADS_DIR, f"{batch_id}_{f.filename}")
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)
        saved_paths.append(save_path)

    if not saved_paths:
        raise HTTPException(status_code=400, detail="No valid PDF documents identified in batch payload.")

    batch_tasks[batch_id] = {
        "batch_id": batch_id,
        "status": "QUEUED",
        "total_files": len(saved_paths),
        "completed_files": 0,
        "progress_percent": 0,
        "results": [],
        "created_at": datetime.now().isoformat(),
    }

    background_tasks.add_task(_process_batch_task, batch_id, saved_paths)

    return {
        "batch_id": batch_id,
        "status": "QUEUED",
        "total_files": len(saved_paths),
        "poll_url": f"/api/tasks/{batch_id}",
    }


@app.get("/api/tasks/{task_id}")
def get_task_status(task_id: str):
    task = batch_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Batch task not found.")
    return task


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
    allowed_exts = [".pdf", ".png", ".jpg", ".jpeg", ".webp"]
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail="Supported formats: PDF, PNG, JPG, JPEG, and WebP invoices.",
        )

    temp_path = os.path.join(UPLOADS_DIR, file.filename)
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        parsed_invoice = extractor.extract_document(temp_path, mime_type=file.content_type)
        contract = _get_contract_pydantic_from_db(db, parsed_invoice.vendor_name)
        if not contract:
            raise HTTPException(status_code=404, detail="No matching contract found in database.")

        report = engine_audit.audit_invoice(parsed_invoice, contract)
        audit_id = _persist_audit_to_db(db, parsed_invoice, report, temp_path)

        return {
            "audit_id": audit_id,
            "document_type": "IMAGE_OCR" if ext != ".pdf" else "PDF_VECTOR",
            "invoice": parsed_invoice.model_dump(),
            "contract": contract.model_dump(),
            "report": report.model_dump(),
            "certificate_url": f"/api/audit/{audit_id}/certificate",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/audit-sample/{sample_type}")
def audit_sample_invoice(sample_type: str, db: Session = Depends(get_db)):
    if sample_type == "valid":
        filename = "invoice_valid.pdf"
    elif sample_type == "scanned":
        filename = "invoice_scanned_receipt.png"
    else:
        filename = "invoice_overcharged.pdf"

    doc_path = os.path.join(SAMPLES_DIR, filename)

    if not os.path.exists(doc_path):
        raise HTTPException(status_code=404, detail=f"Sample invoice {filename} not found.")

    ext = os.path.splitext(filename)[1].lower()
    parsed_invoice = extractor.extract_document(doc_path)
    contract = _get_contract_pydantic_from_db(db, parsed_invoice.vendor_name)
    if not contract:
        raise HTTPException(status_code=404, detail="No matching contract found in database.")

    report = engine_audit.audit_invoice(parsed_invoice, contract)
    audit_id = _persist_audit_to_db(db, parsed_invoice, report, doc_path)

    return {
        "audit_id": audit_id,
        "document_type": "IMAGE_OCR" if ext != ".pdf" else "PDF_VECTOR",
        "invoice": parsed_invoice.model_dump(),
        "contract": contract.model_dump(),
        "report": report.model_dump(),
        "certificate_url": f"/api/audit/{audit_id}/certificate",
    }


@app.post("/api/hitl-decision")
def record_hitl_decision(
    decision: HITLDecisionRequest,
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
    x_user_name: Optional[str] = Header(None, alias="X-User-Name"),
    db: Session = Depends(get_db),
):
    active_role = decision.reviewer_role or x_user_role or "AP_REVIEWER"
    active_name = decision.reviewer_id or x_user_name or "Surya Prakash"

    # 1. Forensic Auditor role is strictly read-only
    if active_role == "AUDITOR_READONLY":
        raise HTTPException(
            status_code=403,
            detail="Forensic Auditor persona is strictly read-only. Decision dispatch is restricted to operational AP Reviewers and Finance Executives.",
        )

    # 2. Executive Overrides require VP Finance clearance
    if decision.action == "APPROVE_OVERCHARGE" and active_role != "FINANCE_VP":
        raise HTTPException(
            status_code=403,
            detail="Executive Overrides for invoice discrepancies require VP Finance authorization under corporate SOX compliance controls. Escalate via Route Workflow instead.",
        )

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
            f"Executive override & exception granted by {active_name} ({active_role}) for #{decision.invoice_number}. "
            f"Invoice marked approved for payment with audit tag."
        )
    elif decision.action == "PARTIAL_APPROVE":
        approved_amt = decision.partial_approved_amount or 0.0
        status_message = (
            f"Partial payment of ${approved_amt:,.2f} authorized for #{decision.invoice_number}. "
            f"Overcharge of ${decision.disputed_amount:,.2f} placed on conditional AP hold pending credit note."
        )
    elif decision.action == "CONDITIONAL_DISPUTE":
        status_message = (
            f"Conditional dispute filed against specific line items on #{decision.invoice_number}. "
            f"Disputed amount (${decision.disputed_amount:,.2f}) withheld pending vendor rate audit."
        )
    elif decision.action == "ROUTE_WORKFLOW":
        target = decision.routing_target or "Legal Counsel"
        status_message = (
            f"Invoice #{decision.invoice_number} routed to {target} for compliance determination. "
            f"Escalation notes attached by {active_name}."
        )
    else:
        status_message = f"Invoice #{decision.invoice_number} rejected and returned to vendor by {active_name}."

    if audit_run:
        hitl_rec = HumanDecisionRecord(
            audit_run_id=audit_run.id,
            reviewer_id=active_name,
            reviewer_role=active_role,
            action=decision.action,
            disputed_amount=decision.disputed_amount,
            reviewer_notes=decision.reviewer_notes or status_message,
        )
        db.add(hitl_rec)
        db.commit()

    # Calculate total blocked savings from database
    total_savings = (
        db.query(HumanDecisionRecord)
        .filter(HumanDecisionRecord.action.in_(["DISPUTE_AND_EMAIL", "REJECT", "PARTIAL_APPROVE", "CONDITIONAL_DISPUTE"]))
        .with_entities(HumanDecisionRecord.disputed_amount)
        .all()
    )
    total_blocked = sum(s[0] for s in total_savings)
    # Auto-dispatch outbound financial webhook
    event_type_map = {
        "DISPUTE_AND_EMAIL": "hitl.decision.dispute_dispatched",
        "APPROVE_OVERCHARGE": "hitl.decision.executive_override",
        "PARTIAL_APPROVE": "hitl.decision.partial_remittance",
        "CONDITIONAL_DISPUTE": "hitl.decision.conditional_dispute",
        "ROUTE_WORKFLOW": "hitl.decision.workflow_routed",
    }
    evt_type = event_type_map.get(decision.action, "hitl.decision.committed")
    webhook_res = dispatch_webhook(
        event_type=evt_type,
        event_data={
            "invoice_number": decision.invoice_number,
            "vendor_name": decision.vendor_name,
            "action": decision.action,
            "disputed_amount": decision.disputed_amount,
            "gross_amount": audit_run.total_billed if audit_run else 0.0,
            "reviewer_name": active_name,
            "reviewer_role": active_role,
            "notes": decision.reviewer_notes or status_message,
        },
        simulate=True
    )
    try:
        wb_rec = WebhookEventRecord(
            event_id=webhook_res["event_id"],
            event_type=evt_type,
            target_url=webhook_res["target_url"],
            signature=webhook_res["signature"],
            payload_json=json.dumps(webhook_res["payload"]),
            status_code=webhook_res["status_code"],
            success=webhook_res["success"],
            simulated=webhook_res["simulated"],
        )
        db.add(wb_rec)
        db.commit()
    except Exception:
        pass

    return {
        "status": "SUCCESS",
        "message": status_message,
        "reviewer": active_name,
        "reviewer_role": active_role,
        "total_savings_to_date": total_blocked,
        "webhook_event": webhook_res,
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


@app.get("/api/analytics/ledger")
def get_analytics_ledger(
    search: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    # 1. High-level KPIs
    total_audits = db.query(AuditRunRecord).count()
    flagged_audits = db.query(AuditRunRecord).filter(AuditRunRecord.status == "FLAGGED").count()
    passed_audits = total_audits - flagged_audits

    gross_billed_query = db.query(func.sum(AuditRunRecord.total_billed)).scalar() or 0.0
    authorized_query = db.query(func.sum(AuditRunRecord.total_expected)).scalar() or 0.0
    total_overcharge_query = db.query(func.sum(AuditRunRecord.total_overcharge)).scalar() or 0.0

    savings_records = (
        db.query(HumanDecisionRecord.disputed_amount)
        .filter(HumanDecisionRecord.action.in_(["DISPUTE_AND_EMAIL", "REJECT", "PARTIAL_APPROVE", "CONDITIONAL_DISPUTE"]))
        .all()
    )
    total_savings_protected = sum(s[0] for s in savings_records)

    compliance_rate = round((passed_audits / max(1, total_audits)) * 100, 1)

    # 2. Top Violated Clauses Breakdown
    discrepancies = db.query(AuditDiscrepancyRecord).all()
    clause_map = {
        "RATE_MISMATCH": {"label": "Schedule A Rate Deviations (§3.1)", "count": 0, "amount": 0.0},
        "UNAPPROVED_FEE": {"label": "Unauthorized Surcharges (§4.2)", "count": 0, "amount": 0.0},
        "HOURS_EXCEEDED": {"label": "Monthly Hours Cap Exceeded", "count": 0, "amount": 0.0},
        "TERM_MISMATCH": {"label": "Payment Terms Conflict (§5.3)", "count": 0, "amount": 0.0},
        "OTHER": {"label": "Contract Spec Deviation", "count": 0, "amount": 0.0},
    }
    for d in discrepancies:
        t = d.discrepancy_type if d.discrepancy_type in clause_map else "OTHER"
        clause_map[t]["count"] += 1
        clause_map[t]["amount"] += (d.overcharge_amount or 0.0)

    # 3. Decision Resolutions Breakdown
    decisions = db.query(HumanDecisionRecord).all()
    action_map = {
        "DISPUTE_AND_EMAIL": {"label": "Full Legal Dispute", "count": 0, "amount": 0.0},
        "PARTIAL_APPROVE": {"label": "Partial Remittance", "count": 0, "amount": 0.0},
        "CONDITIONAL_DISPUTE": {"label": "Conditional AP Hold", "count": 0, "amount": 0.0},
        "ROUTE_WORKFLOW": {"label": "Workflow Escalation", "count": 0, "amount": 0.0},
        "APPROVE_OVERCHARGE": {"label": "Executive Override", "count": 0, "amount": 0.0},
        "REJECT": {"label": "Complete Rejection", "count": 0, "amount": 0.0},
    }
    for dec in decisions:
        a = dec.action if dec.action in action_map else "DISPUTE_AND_EMAIL"
        action_map[a]["count"] += 1
        action_map[a]["amount"] += (dec.disputed_amount or 0.0)

    # 4. Searchable Historical Ledger
    ledger_query = (
        db.query(AuditRunRecord)
        .join(InvoiceRecord)
        .join(VendorRecord)
        .order_by(AuditRunRecord.id.desc())
    )

    if status and status.upper() != "ALL":
        ledger_query = ledger_query.filter(AuditRunRecord.status == status.upper())

    if search:
        search_filter = f"%{search.strip()}%"
        ledger_query = ledger_query.filter(
            or_(
                InvoiceRecord.invoice_number.ilike(search_filter),
                VendorRecord.name.ilike(search_filter),
            )
        )

    ledger_records = ledger_query.limit(100).all()

    ledger_list = []
    for r in ledger_records:
        latest_decision = (
            db.query(HumanDecisionRecord)
            .filter(HumanDecisionRecord.audit_run_id == r.id)
            .order_by(HumanDecisionRecord.id.desc())
            .first()
        )
        ledger_list.append({
            "audit_id": r.id,
            "invoice_number": r.invoice.invoice_number,
            "vendor_name": r.invoice.vendor.name,
            "contract_ref": r.contract.contract_ref if r.contract else "MSA-2025-CS01",
            "status": r.status,
            "total_billed": r.total_billed,
            "total_expected": r.total_expected,
            "total_overcharge": r.total_overcharge,
            "discrepancies_count": len(r.discrepancies),
            "audited_at": r.audited_at.strftime("%Y-%m-%d %H:%M") if r.audited_at else "",
            "decision": {
                "action": latest_decision.action if latest_decision else "PENDING_REVIEW",
                "reviewer_id": latest_decision.reviewer_id if latest_decision else None,
                "notes": latest_decision.reviewer_notes if latest_decision else None,
                "disputed_amount": latest_decision.disputed_amount if latest_decision else 0.0,
            } if latest_decision else None,
            "certificate_url": f"/api/audit-certificate/{r.invoice.invoice_number}",
        })

    return {
        "kpis": {
            "total_audits": total_audits,
            "passed_audits": passed_audits,
            "flagged_audits": flagged_audits,
            "compliance_rate": compliance_rate,
            "total_gross_billed": round(gross_billed_query, 2),
            "total_authorized": round(authorized_query, 2),
            "total_overcharge_identified": round(total_overcharge_query, 2),
            "total_savings_protected": round(total_savings_protected, 2),
            "avg_latency_ms": 0.15,
        },
        "clause_breakdown": clause_map,
        "action_breakdown": action_map,
        "audit_ledger": ledger_list,
    }


@app.get("/api/vendors/risk-matrix")
def get_vendor_risk_matrix_endpoint(db: Session = Depends(get_db)):
    """
    Fleet-wide Supplier Risk Intelligence & Reliability Matrix.
    """
    return get_fleet_vendor_risk_matrix(db)


@app.get("/api/vendors/{vendor_id}/risk-profile")
def get_vendor_risk_profile_endpoint(vendor_id: int, db: Session = Depends(get_db)):
    """
    Granular Behavioral Fraud & Reliability Dossier for a specific supplier by ID.
    """
    profile = calculate_vendor_risk_profile(db, vendor_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    return profile


@app.get("/api/vendors/by-name/{vendor_name}/risk-profile")
def get_vendor_risk_profile_by_name_endpoint(vendor_name: str, db: Session = Depends(get_db)):
    """
    Granular Behavioral Fraud & Reliability Dossier for a supplier by name.
    """
    vendor = db.query(VendorRecord).filter(VendorRecord.name.ilike(f"%{vendor_name}%")).first()
    if not vendor:
        raise HTTPException(status_code=404, detail=f"Vendor '{vendor_name}' not found.")
    profile = calculate_vendor_risk_profile(db, vendor.id)
    return profile


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
    invoice_date: Optional[str] = "2025-02-01"
    due_date: Optional[str] = "2025-02-16"
    payment_terms: Optional[str] = "Net 15"
    line_items: Optional[List[Dict[str, Any]]] = None
    discrepancies: Optional[List[Any]] = None
    api_key: Optional[str] = None


copilot_instance = None

def get_copilot(api_key: Optional[str] = None):
    global copilot_instance
    if api_key:
        from src.copilot import AuditCopilot
        return AuditCopilot(api_key=api_key)
    if copilot_instance is None:
        from src.copilot import AuditCopilot
        copilot_instance = AuditCopilot()
    return copilot_instance


@app.post("/api/copilot/chat")
def copilot_chat(req: CopilotChatRequest, db: Session = Depends(get_db)):
    contract = _get_contract_pydantic_from_db(db, req.vendor_name)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found for vendor.")

    # Reconstruct line items
    parsed_line_items = []
    if req.line_items:
        for item in req.line_items:
            qty = float(item.get("quantity", 1.0))
            price = float(item.get("unit_price", 0.0))
            tot = float(item.get("total_price") or item.get("total") or (qty * price))
            parsed_line_items.append(
                InvoiceLineItem(
                    description=str(item.get("description", "")),
                    quantity=qty,
                    unit_price=price,
                    total_price=tot,
                )
            )
    else:
        # Check if invoice exists in DB
        db_inv = db.query(InvoiceRecord).filter(InvoiceRecord.invoice_number == req.invoice_number).first()
        if db_inv and db_inv.line_items:
            for li in db_inv.line_items:
                parsed_line_items.append(
                    InvoiceLineItem(
                        description=li.description,
                        quantity=li.quantity,
                        unit_price=li.unit_price,
                        total_price=li.total_price,
                    )
                )
        else:
            parsed_line_items = [
                InvoiceLineItem(description="Senior Cloud DevOps Architect", quantity=80.0, unit_price=95.0, total_price=7600.0),
                InvoiceLineItem(description="QA Automation Engineer", quantity=40.0, unit_price=65.0, total_price=2600.0),
                InvoiceLineItem(description="Platform Maintenance & On-Call Emergency Surcharge", quantity=1.0, unit_price=350.0, total_price=350.0),
            ]

    # Reconstruct discrepancies
    structured_discrepancies = []
    if req.discrepancies:
        for d in req.discrepancies:
            if isinstance(d, dict):
                structured_discrepancies.append(
                    DiscrepancyItem(
                        type=d.get("type", DiscrepancyType.RATE_MISMATCH),
                        description=d.get("description", ""),
                        billed_amount=float(d.get("billed_amount", 0.0)),
                        expected_amount=float(d.get("expected_amount", 0.0)),
                        overcharge=float(d.get("overcharge", 0.0)),
                    )
                )
            elif isinstance(d, str):
                structured_discrepancies.append(
                    DiscrepancyItem(
                        type=DiscrepancyType.RATE_MISMATCH,
                        description=d,
                        billed_amount=0.0,
                        expected_amount=0.0,
                        overcharge=0.0,
                    )
                )
    else:
        db_run = (
            db.query(AuditRunRecord)
            .join(InvoiceRecord)
            .filter(InvoiceRecord.invoice_number == req.invoice_number)
            .order_by(AuditRunRecord.id.desc())
            .first()
        )
        if db_run and db_run.discrepancies:
            for disc in db_run.discrepancies:
                structured_discrepancies.append(
                    DiscrepancyItem(
                        type=disc.discrepancy_type or DiscrepancyType.RATE_MISMATCH,
                        description=disc.description,
                        billed_amount=disc.billed_amount or 0.0,
                        expected_amount=disc.expected_amount or 0.0,
                        overcharge=disc.overcharge_amount or 0.0,
                    )
                )

    invoice = ParsedInvoice(
        vendor_name=req.vendor_name,
        invoice_number=req.invoice_number,
        invoice_date=req.invoice_date or "2025-02-01",
        due_date=req.due_date or "2025-02-16",
        payment_terms=req.payment_terms or "Net 15",
        line_items=parsed_line_items,
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
        discrepancies=structured_discrepancies,
    )

    copilot = get_copilot(api_key=req.api_key)
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


@app.post("/api/erp/export")
def export_erp_journal(
    req: ERPExportRequest,
    db: Session = Depends(get_db),
):
    audit_rec = (
        db.query(AuditRunRecord)
        .join(InvoiceRecord)
        .filter(InvoiceRecord.invoice_number == req.invoice_number)
        .order_by(AuditRunRecord.id.desc())
        .first()
    )
    if not audit_rec:
        raise HTTPException(status_code=404, detail="Invoice or audit run not found.")

    invoice_rec = audit_rec.invoice
    latest_decision = (
        db.query(HumanDecisionRecord)
        .filter(HumanDecisionRecord.audit_run_id == audit_rec.id)
        .order_by(HumanDecisionRecord.id.desc())
        .first()
    )

    invoice_data = {
        "invoice_number": invoice_rec.invoice_number,
        "vendor_name": invoice_rec.vendor.name if invoice_rec.vendor else "ACME Corporation",
        "invoice_date": invoice_rec.invoice_date or "2025-02-01",
        "due_date": invoice_rec.due_date or "2025-03-03",
        "payment_terms": invoice_rec.payment_terms or "Net 30",
        "currency": invoice_rec.currency or "USD",
        "total_amount": invoice_rec.total_amount,
    }

    audit_data = {
        "status": audit_rec.status,
        "total_billed": audit_rec.total_billed,
        "total_expected": audit_rec.total_expected,
        "total_overcharge": audit_rec.total_overcharge,
        "discrepancies": [
            {
                "type": d.discrepancy_type,
                "description": d.description,
                "overcharge": d.overcharge_amount,
            }
            for d in audit_rec.discrepancies
        ],
    }

    decision_data = None
    if latest_decision:
        decision_data = {
            "action": latest_decision.action,
            "disputed_amount": latest_decision.disputed_amount,
            "reviewer_id": latest_decision.reviewer_id,
            "reviewer_role": latest_decision.reviewer_role,
        }

    export_result = generate_erp_export(
        invoice_data=invoice_data,
        audit_data=audit_data,
        decision_data=decision_data,
        erp_system=req.erp_system,
        format_type=req.format,
    )

    # Save export log to database
    export_rec = ERPExportRecord(
        invoice_id=invoice_rec.id,
        erp_system=export_result["erp_system"],
        export_format=export_result["format"],
        filename=export_result["filename"],
        exported_by=req.reviewer_id or "Surya Prakash",
    )
    db.add(export_rec)
    db.commit()

    return export_result


@app.get("/api/erp/history")
def get_erp_export_history(db: Session = Depends(get_db)):
    records = db.query(ERPExportRecord).order_by(ERPExportRecord.id.desc()).limit(20).all()
    return {
        "exports": [
            {
                "id": r.id,
                "invoice_number": r.invoice.invoice_number if r.invoice else "UNKNOWN",
                "erp_system": r.erp_system,
                "export_format": r.export_format,
                "filename": r.filename,
                "exported_by": r.exported_by,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
            }
            for r in records
        ]
    }


@app.post("/api/webhooks/dispatch")
def test_dispatch_webhook(
    req: WebhookDispatchRequest,
    db: Session = Depends(get_db),
):
    audit_rec = (
        db.query(AuditRunRecord)
        .join(InvoiceRecord)
        .filter(InvoiceRecord.invoice_number == req.invoice_number)
        .order_by(AuditRunRecord.id.desc())
        .first()
    )

    gross = audit_rec.total_billed if audit_rec else 10950.0
    disputed = audit_rec.total_overcharge if audit_rec else 1550.0
    vendor_name = (
        audit_rec.invoice.vendor.name
        if audit_rec and audit_rec.invoice and audit_rec.invoice.vendor
        else "ACME Corporation"
    )

    event_data = {
        "invoice_number": req.invoice_number,
        "vendor_name": vendor_name,
        "gross_amount": gross,
        "disputed_amount": disputed,
        "reviewer_name": "Surya Prakash",
        "reviewer_role": "Accounts Payable Specialist",
        "timestamp": datetime.utcnow().isoformat(),
    }

    result = dispatch_webhook(
        event_type=req.event_type,
        event_data=event_data,
        target_url=req.target_url,
        simulate=req.simulate,
    )

    wb_rec = WebhookEventRecord(
        event_id=result["event_id"],
        event_type=req.event_type,
        target_url=result["target_url"],
        signature=result["signature"],
        payload_json=json.dumps(result["payload"]),
        status_code=result["status_code"],
        success=result["success"],
        simulated=result["simulated"],
    )
    db.add(wb_rec)
    db.commit()

    return result


@app.get("/api/webhooks/history")
def get_webhook_history(db: Session = Depends(get_db)):
    events = db.query(WebhookEventRecord).order_by(WebhookEventRecord.id.desc()).limit(20).all()
    return {
        "webhooks": [
            {
                "id": e.id,
                "event_id": e.event_id,
                "event_type": e.event_type,
                "target_url": e.target_url,
                "signature": e.signature,
                "status_code": e.status_code,
                "success": e.success,
                "simulated": e.simulated,
                "created_at": e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "",
            }
            for e in events
        ]
    }


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    dashboard_file = os.path.join(BASE_DIR, "src", "dashboard.html")
    if os.path.exists(dashboard_file):
        with open(dashboard_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Veritas AP Compliance System</h1><p>dashboard.html not found</p>"
