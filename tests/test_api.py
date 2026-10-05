import pytest
from fastapi.testclient import TestClient
from src.server import app

client = TestClient(app)


def test_api_list_contracts():
    response = client.get("/api/contracts")
    assert response.status_code == 200
    data = response.json()
    assert "contracts" in data
    assert len(data["contracts"]) >= 1
    assert data["contracts"][0]["vendor_name"] == "CloudScale Innovations"


def test_api_audit_sample_valid():
    response = client.post("/api/audit-sample/valid")
    assert response.status_code == 200
    data = response.json()
    assert data["report"]["status"] == "PASSED"
    assert data["report"]["total_overcharge"] == 0.0


def test_api_audit_sample_overcharged():
    response = client.post("/api/audit-sample/overcharged")
    assert response.status_code == 200
    data = response.json()
    assert data["report"]["status"] == "FLAGGED"
    assert data["report"]["total_overcharge"] == 1550.0
    assert len(data["report"]["discrepancies"]) == 3


def test_api_hitl_decision_dispute():
    # First run audit to ensure invoice exists in DB
    client.post("/api/audit-sample/overcharged")

    decision_payload = {
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "action": "DISPUTE_AND_EMAIL",
        "disputed_amount": 1550.0,
        "dispute_email_content": "Dispute notice test",
        "reviewer_notes": "Automated integration test",
    }
    response = client.post("/api/hitl-decision", json=decision_payload)
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "SUCCESS"
    assert res["total_savings_to_date"] >= 1550.0


def test_api_metrics_endpoint():
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "total_audits" in data
    assert "total_savings_blocked" in data
    assert data["total_audits"] >= 1


def test_api_evals_benchmark():
    response = client.get("/api/evals/benchmark")
    assert response.status_code == 200
    data = response.json()
    assert data["total_cases"] == 20
    assert data["precision"] == 100.0
    assert data["recall"] == 100.0


def test_api_hitl_partial_approval():
    client.post("/api/audit-sample/overcharged")
    payload = {
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "action": "PARTIAL_APPROVE",
        "disputed_amount": 1550.0,
        "partial_approved_amount": 3200.0,
        "dispute_email_content": "Vendor credit memo required for balance",
        "reviewer_notes": "Partial approval test",
    }
    response = client.post("/api/hitl-decision", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "Partial payment" in data["message"]
    assert "authorized" in data["message"]


def test_api_hitl_conditional_dispute():
    client.post("/api/audit-sample/overcharged")
    payload = {
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "action": "CONDITIONAL_DISPUTE",
        "disputed_amount": 1550.0,
        "reviewer_notes": "Conditional hold under §4.2 review",
    }
    response = client.post("/api/hitl-decision", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "Conditional dispute" in data["message"]
    assert "withheld" in data["message"]


def test_api_hitl_route_workflow():
    client.post("/api/audit-sample/overcharged")
    payload = {
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "action": "ROUTE_WORKFLOW",
        "disputed_amount": 1550.0,
        "routing_target": "Legal & General Counsel",
        "reviewer_notes": "Escalated for clause §4.2 review",
    }
    response = client.post("/api/hitl-decision", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "routed to Legal & General Counsel" in data["message"]


def test_api_batch_upload_and_task_polling():
    import os
    sample_pdf_path = os.path.join("data", "sample_invoices", "invoice_valid.pdf")
    with open(sample_pdf_path, "rb") as f:
        file_bytes = f.read()

    files = [("files", ("test_batch_1.pdf", file_bytes, "application/pdf"))]
    response = client.post("/api/audit-batch", files=files)
    assert response.status_code == 200
    data = response.json()
    assert "batch_id" in data
    assert data["total_files"] == 1
    
    # Poll task status
    task_id = data["batch_id"]
    status_resp = client.get(f"/api/tasks/{task_id}")
    assert status_resp.status_code == 200
    task_data = status_resp.json()
    assert task_data["batch_id"] == task_id
    assert task_data["status"] in ["QUEUED", "PROCESSING", "COMPLETED"]


def test_api_analytics_ledger():
    # Ingest a sample to guarantee audit records exist
    client.post("/api/audit-sample/overcharged")

    response = client.get("/api/analytics/ledger")
    assert response.status_code == 200
    data = response.json()

    # Verify KPI schema
    assert "kpis" in data
    kpis = data["kpis"]
    assert kpis["total_audits"] >= 1
    assert kpis["total_gross_billed"] > 0
    assert kpis["avg_latency_ms"] == 0.15
    assert "compliance_rate" in kpis

    # Verify Clause Breakdown schema
    assert "clause_breakdown" in data
    assert "RATE_MISMATCH" in data["clause_breakdown"]
    assert "UNAPPROVED_FEE" in data["clause_breakdown"]

    # Verify Action Breakdown schema
    assert "action_breakdown" in data
    assert "DISPUTE_AND_EMAIL" in data["action_breakdown"]

    # Verify Audit Ledger array
    assert "audit_ledger" in data
    assert len(data["audit_ledger"]) >= 1
    first = data["audit_ledger"][0]
    assert "invoice_number" in first
    assert "vendor_name" in first
    assert "total_billed" in first
    assert "certificate_url" in first


def test_api_analytics_ledger_filtering():
    # Filter by FLAGGED status
    response = client.get("/api/analytics/ledger?status=FLAGGED")
    assert response.status_code == 200
    data = response.json()
    for row in data["audit_ledger"]:
        assert row["status"] == "FLAGGED"

    # Search filter
    response_search = client.get("/api/analytics/ledger?search=CloudScale")
    assert response_search.status_code == 200
    data_search = response_search.json()
    for row in data_search["audit_ledger"]:
        assert "cloudscale" in row["vendor_name"].lower() or "cloudscale" in row["invoice_number"].lower()


def test_api_copilot_payment_terms_qa():
    payload = {
        "message": "What are the payment terms under §5.3?",
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "billed_total": 10550.0,
        "authorized_total": 9000.0,
        "current_overcharge": 1550.0,
    }
    response = client.post("/api/copilot/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    reply = data["reply"]
    assert "Section 5.3" in reply
    assert "Net 30" in reply
    assert "Net 15" in reply


def test_api_copilot_dynamic_rate_compromise():
    payload = {
        "message": "Can we compromise at $85/hr for Senior DevOps?",
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "billed_total": 10550.0,
        "authorized_total": 9000.0,
        "current_overcharge": 1550.0,
    }
    response = client.post("/api/copilot/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    # At $85/hr: billed is $95/hr, so deduction is (95 - 85) * 80 = $800 + $350 fee = $1,150.00
    assert data["adjusted_overcharge"] == 1150.0
    assert data["revised_draft"] is not None
    assert "$85.00/hr" in data["revised_draft"]
    assert "1,150.00" in data["revised_draft"]
    assert "$85.00/hr" in data["reply"]


def test_api_copilot_labor_rates_qa():
    payload = {
        "message": "What is the Senior DevOps rate under Section 3.1 & Schedule A?",
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "billed_total": 10550.0,
        "authorized_total": 9000.0,
        "current_overcharge": 1550.0,
    }
    response = client.post("/api/copilot/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "Section 3.1" in data["reply"]
    assert "$80.00/hr" in data["reply"]
    assert "$95.00/hr" in data["reply"]
    assert "1,200.00" in data["reply"]


def test_api_copilot_action_guidance():
    payload = {
        "message": "What should I do to resolve this invoice?",
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "billed_total": 10550.0,
        "authorized_total": 9000.0,
        "current_overcharge": 1550.0,
    }
    response = client.post("/api/copilot/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "Full Legal Dispute" in data["reply"]
    assert "Partial Remittance" in data["reply"]
    assert "Conditional AP Hold" in data["reply"]


def test_api_copilot_strict_legal_tone():
    payload = {
        "message": "Draft this in a strict legal demand notice tone",
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "billed_total": 10550.0,
        "authorized_total": 9000.0,
        "current_overcharge": 1550.0,
    }
    response = client.post("/api/copilot/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["revised_draft"] is not None
    assert "FORMAL NOTICE OF DISCREPANCY & AUDIT HOLD" in data["revised_draft"]
def test_rbac_list_users():
    response = client.get("/api/auth/users")
    assert response.status_code == 200
    data = response.json()
    assert "users" in data
    assert len(data["users"]) >= 3
    roles = [u["role"] for u in data["users"]]
    assert "AP_REVIEWER" in roles
    assert "FINANCE_VP" in roles
    assert "AUDITOR_READONLY" in roles


def test_rbac_get_me_profile():
    # Test default
    res_default = client.get("/api/auth/me")
    assert res_default.status_code == 200
    d_def = res_default.json()
    assert d_def["username"] == "surya.prakash"
    assert d_def["permissions"]["can_approve_override"] is False
    assert d_def["permissions"]["is_readonly"] is False

    # Test VP profile via header
    res_vp = client.get("/api/auth/me", headers={"X-User-Username": "elena.rostova"})
    assert res_vp.status_code == 200
    d_vp = res_vp.json()
    assert d_vp["username"] == "elena.rostova"
    assert d_vp["role"] == "FINANCE_VP"
    assert d_vp["permissions"]["can_approve_override"] is True

    # Test Auditor profile
    res_auditor = client.get("/api/auth/me", headers={"X-User-Username": "marcus.vance"})
    assert res_auditor.status_code == 200
    d_aud = res_auditor.json()
    assert d_aud["role"] == "AUDITOR_READONLY"
    assert d_aud["permissions"]["is_readonly"] is True
    assert d_aud["permissions"]["can_dispute"] is False


def test_rbac_ap_reviewer_blocked_from_override():
    payload = {
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "action": "APPROVE_OVERCHARGE",
        "disputed_amount": 1550.0,
        "reviewer_id": "Surya Prakash",
        "reviewer_role": "AP_REVIEWER",
    }
    response = client.post("/api/hitl-decision", json=payload)
    assert response.status_code == 403
    assert "Executive Overrides" in response.json()["detail"]


def test_rbac_finance_vp_can_approve_override():
    payload = {
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "action": "APPROVE_OVERCHARGE",
        "disputed_amount": 1550.0,
        "reviewer_id": "Elena Rostova",
        "reviewer_role": "FINANCE_VP",
    }
    response = client.post("/api/hitl-decision", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["reviewer_role"] == "FINANCE_VP"


def test_rbac_readonly_auditor_blocked_from_decision():
    payload = {
        "invoice_number": "INV-2025-094",
        "vendor_name": "CloudScale Innovations",
        "action": "DISPUTE_AND_EMAIL",
        "disputed_amount": 1550.0,
        "reviewer_id": "Marcus Vance",
        "reviewer_role": "AUDITOR_READONLY",
    }
    response = client.post("/api/hitl-decision", json=payload)
    assert response.status_code == 403
    assert "Forensic Auditor persona is strictly read-only" in response.json()["detail"]




