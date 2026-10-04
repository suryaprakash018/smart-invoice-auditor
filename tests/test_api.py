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

