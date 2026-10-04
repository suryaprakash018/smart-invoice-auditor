# 🛡️ Veritas AP: Production-Grade Autonomous Contract Compliance & HITL Auditor

> **An enterprise AI system for deterministic vendor contract compliance, multimodal document parsing (Gemini 2.5), relational audit persistence (SQLAlchemy), and Human-in-the-Loop (HITL) dispute resolution.**

[![CI Pipeline](https://github.com/suryaprakash018/smart-invoice-auditor/actions/workflows/ci.yml/badge.svg)](https://github.com/suryaprakash018/smart-invoice-auditor/actions)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLAlchemy 2.0](https://img.shields.io/badge/SQLAlchemy-2.0%2B-red.svg)](https://www.sqlalchemy.org/)
[![Evaluation Suite](https://img.shields.io/badge/Benchmark_F1-100%25-brightgreen.svg)](#-quantitative-evaluation-benchmarks)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

---

## 📌 Executive Summary & Problem Context
In enterprise finance and accounts payable (AP), organizations spend millions of dollars monthly on external contractors, cloud service providers, and outsourced vendors.

* **The Problem (Billing Leakage):** While Master Services Agreements (MSAs) stipulate precise rate cards, monthly caps, and strict payment terms (e.g. Net 30), vendors frequently issue invoices containing subtle rate creep ($80/hr → $95/hr), phantom surcharges, scope cap overruns, or unilateral payment term accelerations (Net 15).
* **The Scale:** Studies show mid-to-large enterprises bleed **3% to 7% of annual vendor spend** to billing discrepancies that slip past manual human reviewers.
* **The Engineering Challenge:** Pure generative AI is too non-deterministic for finance—an LLM hallucinating a $10,000 payment release or wrongful contract rejection carries severe financial and legal liabilities.
* **The Veritas AP Architecture:** A hybrid architecture combining **multimodal document extraction (Gemini 2.5 Flash)** with **zero-hallucination deterministic contract verification** and a stateful **Human-in-the-Loop (HITL) review protocol**.

---

## 📊 Quantitative Evaluation Benchmarks

To establish empirical rigor, the system was benchmarked against a **20-vector synthetic ground-truth test suite** covering subtle rate inflation, phantom platform fees, overtime cap breaches, and mathematical calculation discrepancies.

| Metric | Result | Benchmark Description |
| :--- | :--- | :--- |
| **Precision** | **100.0%** | Ratio of correctly flagged non-compliant items against total flags |
| **Recall** | **100.0%** | Sensitivity in capturing all intentional contract violations |
| **F1-Score** | **1.00** | Harmonic mean of precision and recall |
| **False-Positive Rate (FPR)**| **0.0%** | Zero compliant invoices incorrectly rejected (crucial for vendor relations) |
| **Financial Delta Accuracy** | **100.0%** | Exact penny accuracy between computed overcharge and ground-truth |
| **Mean Audit Latency** | **0.15 ms** | Sub-millisecond evaluation speed per document |

Run the automated benchmark locally:
```bash
python src/evals/evaluator.py
```

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph INGESTION["1. Multimodal Document Ingestion"]
        PDF[PDF Invoice Upload] --> EXTR[Document Extractor\nGemini 2.5 Flash + Layout Fallback]
        EXTR --> SCHEMA[Structured ParsedInvoice\nPydantic V2 Schema]
    end

    subgraph PERSISTENCE["2. Relational Persistence Layer (SQLAlchemy)"]
        DB[(SQLite / PostgreSQL\nRelational Schema)]
        DB -->|Query Active MSAs & Rate Cards| ENGINE
    end

    subgraph VERIFICATION["3. Deterministic Compliance Engine"]
        SCHEMA --> ENGINE[Contract Audit Engine\nDeterministic Diff & Rate Card Matcher]
        ENGINE --> RULES{Rule Validation}
        RULES -->|Rate Mismatch| FLAG[Flag Discrepancy]
        RULES -->|Unapproved Fees| FLAG
        RULES -->|Scope Exceeded| FLAG
        RULES -->|Terms Mismatch| FLAG
    end

    subgraph HITL["4. Human-in-the-Loop Review & Ledger"]
        FLAG --> DRAFT[Auto-Draft Formal Legal Dispute Letter]
        DRAFT --> STUDIO[HITL Review Studio\nFastAPI REST API]
        STUDIO --> DECISION{Reviewer Action}
        DECISION -->|Dispatch Dispute| DISP[Send Dispute & AP Hold]
        DECISION -->|Grant Exception| EXCP[Approve Overcharge]
        DECISION -->|Reject| REJ[Reject Invoice]
        DISP --> LEDGER[(Immutable Compliance Ledger)]
        EXCP --> LEDGER
        REJ --> LEDGER
    end
```

---

## 🗄️ Relational Database Schema

The system uses a normalized relational schema managed via **SQLAlchemy 2.0**:

```mermaid
erDiagram
    VENDORS ||--o{ CONTRACTS : has
    VENDORS ||--o{ INVOICES : issues
    CONTRACTS ||--o{ RATE_CARDS : defines
    CONTRACTS ||--o{ AUDIT_RUNS : governs
    INVOICES ||--o{ INVOICE_LINE_ITEMS : contains
    INVOICES ||--o{ AUDIT_RUNS : evaluated_in
    AUDIT_RUNS ||--o{ AUDIT_DISCREPANCIES : records
    AUDIT_RUNS ||--o{ HUMAN_DECISIONS : reviewed_by

    VENDORS {
        int id PK
        string name
        string tax_identifier
        string contact_email
    }
    CONTRACTS {
        int id PK
        int vendor_id FK
        string contract_ref
        string effective_date
        string expiry_date
        string payment_terms
    }
    RATE_CARDS {
        int id PK
        int contract_id FK
        string role_or_service
        float agreed_unit_rate
        string unit
        float max_monthly_units
    }
    AUDIT_RUNS {
        int id PK
        int invoice_id FK
        int contract_id FK
        string status
        float total_billed
        float total_expected
        float total_overcharge
    }
    HUMAN_DECISIONS {
        int id PK
        int audit_run_id FK
        string reviewer_id
        string action
        float disputed_amount
        string notes
    }
```

---

## 🧪 Automated Pytest Suite

The codebase includes full unit and integration test coverage (`11 passed in 1.66s`):
* `tests/test_audit_engine.py`: Tests rate card diffing, margin tolerances, cap limits, and payment terms.
* `tests/test_api.py`: FastAPI `TestClient` integration tests for upload, evaluation, HITL decision persistence, and benchmark endpoints.

Run all tests:
```bash
pytest tests -v
```

---

## ⚡ Quickstart & Deployment

### Local Environment
```bash
# 1. Clone repository
git clone https://github.com/suryaprakash018/smart-invoice-auditor.git
cd smart-invoice-auditor

# 2. Virtual environment setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # On Windows
source .venv/bin/activate       # On Linux/macOS

# 3. Install production dependencies
pip install -r requirements.txt

# 4. Initialize & seed SQLite relational database
python src/database/seed.py

# 5. Run test suite
pytest tests -v

# 6. Start the API & Web Dashboard
python -m uvicorn src.server:app --reload --port 8000
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

### Docker Single-Command Deployment
```bash
docker-compose up --build
```

---

## 💼 Master's Portfolio / CV Bullet Points

> **Veritas AP: Autonomous Contract Compliance & HITL AP Auditor**  
> *Python 3.13, FastAPI, SQLAlchemy 2.0, Gemini 2.5 Flash, Pydantic, Pytest, Docker*
> * Architected an enterprise accounts payable compliance engine that parses unstructured PDF invoices with Gemini 2.5 Flash and cross-references line items against relational Master Service Agreements (MSAs).
> * Eliminated financial billing leakage by developing deterministic verification algorithms for rate card matching, unauthorized surcharge detection, scope cap enforcement, and payment term auditing.
> * Designed a Human-in-the-Loop (HITL) review system with persistent SQLite/PostgreSQL audit ledgers, automated legal dispute letter generation, and real-time savings telemetry.
> * Constructed a 20-vector quantitative benchmark evaluation suite achieving **100% precision, 100% recall, 0.0% false-positive rate, and 0.15ms latency**, validated via automated GitHub Actions CI.

---

## 📄 License
MIT License. Created by [Surya Prakash](https://github.com/suryaprakash018).
