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
