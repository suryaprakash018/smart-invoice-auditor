import os
import sys
import json
import shutil
from typing import Optional, List
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.models import VendorContract, AuditReport, AuditStatus
from src.extractor import InvoiceExtractor
from src.audit_engine import ContractAuditEngine

app = FastAPI(
    title="Smart Invoice & Contract Audit API",
    description="Autonomous vendor compliance auditor with Human-in-the-Loop approval workflows",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONTRACTS_DIR = os.path.join(BASE_DIR, "data", "contracts")
SAMPLES_DIR = os.path.join(BASE_DIR, "data", "sample_invoices")
UPLOADS_DIR = os.path.join(BASE_DIR, "data", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# In-memory session store for audit log & metrics
AUDIT_HISTORY: List[dict] = []
TOTAL_OVERCHARGES_BLOCKED = 0.0

extractor = InvoiceExtractor()
engine = ContractAuditEngine()


def get_contract_for_vendor(vendor_name: str) -> Optional[VendorContract]:
    for filename in os.listdir(CONTRACTS_DIR):
        if filename.endswith(".json"):
            with open(os.path.join(CONTRACTS_DIR, filename), "r", encoding="utf-8") as f:
                data = json.load(f)
                contract = VendorContract(**data)
                if (
                    contract.vendor_name.lower() in vendor_name.lower()
                    or vendor_name.lower() in contract.vendor_name.lower()
                ):
                    return contract
    # Default fallback to first contract
    files = [f for f in os.listdir(CONTRACTS_DIR) if f.endswith(".json")]
    if files:
        with open(os.path.join(CONTRACTS_DIR, files[0]), "r", encoding="utf-8") as f:
            return VendorContract(**json.load(f))
    return None


class HITLDecisionRequest(BaseModel):
    invoice_number: str
    vendor_name: str
    action: str  # "APPROVE_OVERCHARGE", "DISPUTE_AND_EMAIL", "REJECT"
    disputed_amount: float
    dispute_email_content: Optional[str] = None
    reviewer_notes: Optional[str] = None


@app.get("/api/contracts")
def list_contracts():
    contracts = []
    for filename in os.listdir(CONTRACTS_DIR):
        if filename.endswith(".json"):
            with open(os.path.join(CONTRACTS_DIR, filename), "r", encoding="utf-8") as f:
                contracts.append(json.load(f))
    return {"contracts": contracts}


@app.post("/api/audit-upload")
async def audit_uploaded_invoice(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF invoices are currently supported.")

    temp_path = os.path.join(UPLOADS_DIR, file.filename)
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        parsed_invoice = extractor.extract_from_pdf(temp_path)
        contract = get_contract_for_vendor(parsed_invoice.vendor_name)
        if not contract:
            raise HTTPException(status_code=404, detail=f"No matching contract found for vendor '{parsed_invoice.vendor_name}'")

        report = engine.audit_invoice(parsed_invoice, contract)
        return {
            "invoice": parsed_invoice.model_dump(),
            "contract": contract.model_dump(),
            "report": report.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/audit-sample/{sample_type}")
def audit_sample_invoice(sample_type: str):
    filename = "invoice_valid.pdf" if sample_type == "valid" else "invoice_overcharged.pdf"
    pdf_path = os.path.join(SAMPLES_DIR, filename)

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Sample invoice not found. Run generation script first.")

    parsed_invoice = extractor.extract_from_pdf(pdf_path)
    contract = get_contract_for_vendor(parsed_invoice.vendor_name)
    if not contract:
        raise HTTPException(status_code=404, detail="No contract found for vendor.")

    report = engine.audit_invoice(parsed_invoice, contract)
    return {
        "invoice": parsed_invoice.model_dump(),
        "contract": contract.model_dump(),
        "report": report.model_dump(),
    }


@app.post("/api/hitl-decision")
def record_hitl_decision(decision: HITLDecisionRequest):
    global TOTAL_OVERCHARGES_BLOCKED

    if decision.action == "DISPUTE_AND_EMAIL":
        TOTAL_OVERCHARGES_BLOCKED += decision.disputed_amount
        status_message = (
            f"Formal dispute notice dispatched to {decision.vendor_name}. "
            f"Accounts Payable hold placed on invoice #{decision.invoice_number}. "
            f"Blocked Overcharge: ${decision.disputed_amount:,.2f}."
        )
    elif decision.action == "APPROVE_OVERCHARGE":
        status_message = (
            f"Manual exception granted by reviewer for #{decision.invoice_number}. "
            f"Invoice marked approved for payment with warning tag."
        )
    else:
        TOTAL_OVERCHARGES_BLOCKED += decision.disputed_amount
        status_message = f"Invoice #{decision.invoice_number} rejected and returned to vendor."

    log_entry = {
        "invoice_number": decision.invoice_number,
        "vendor_name": decision.vendor_name,
        "action": decision.action,
        "disputed_amount": decision.disputed_amount,
        "notes": decision.reviewer_notes,
        "status_message": status_message,
    }
    AUDIT_HISTORY.append(log_entry)

    return {
        "status": "SUCCESS",
        "message": status_message,
        "total_savings_to_date": TOTAL_OVERCHARGES_BLOCKED,
    }


@app.get("/api/metrics")
def get_metrics():
    return {
        "total_savings_blocked": TOTAL_OVERCHARGES_BLOCKED,
        "total_decisions_recorded": len(AUDIT_HISTORY),
        "history": AUDIT_HISTORY,
    }


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    dashboard_file = os.path.join(BASE_DIR, "src", "dashboard.html")
    if os.path.exists(dashboard_file):
        with open(dashboard_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Smart Invoice Auditor Dashboard</h1><p>dashboard.html not found</p>"
