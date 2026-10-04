import os
import sys
import time
from typing import List, Dict, Any
from dataclasses import dataclass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.models import (
    ParsedInvoice,
    InvoiceLineItem,
    VendorContract,
    ContractRate,
    AuditStatus,
    DiscrepancyType,
)
from src.audit_engine import ContractAuditEngine


@dataclass
class TestCase:
    id: str
    description: str
    invoice: ParsedInvoice
    expected_status: AuditStatus
    expected_overcharge: float
    expected_violation_types: List[DiscrepancyType]


class ComplianceEvaluator:
    def __init__(self, contract: VendorContract):
        self.contract = contract
        self.engine = ContractAuditEngine()

    def build_test_suite(self) -> List[TestCase]:
        """
        Synthesizes a 20-case ground-truth evaluation suite covering edge cases,
        sneaky rate creep, phantom fees, scope caps, and math errors.
        """
        cases = []

        # 1. Perfectly Compliant Base Cases
        cases.append(TestCase(
            id="TC-01",
            description="Perfect compliance: 80 hrs Senior DevOps @ $80/hr, Net 30",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-01",
                payment_terms="Net 30",
                line_items=[InvoiceLineItem(description="Senior DevOps Engineer", quantity=80, unit_price=80, total_price=6400)],
                subtotal=6400, tax_amount=0, total_amount=6400,
            ),
            expected_status=AuditStatus.PASSED,
            expected_overcharge=0.0,
            expected_violation_types=[],
        ))

        cases.append(TestCase(
            id="TC-02",
            description="Perfect compliance: Multi-role QA (100 hrs @ $55) + Solutions Architect (40 hrs @ $120)",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-02",
                payment_terms="Net 30",
                line_items=[
                    InvoiceLineItem(description="QA Automation Engineer", quantity=100, unit_price=55, total_price=5500),
                    InvoiceLineItem(description="Cloud Solutions Architect", quantity=40, unit_price=120, total_price=4800),
                ],
                subtotal=10300, tax_amount=0, total_amount=10300,
            ),
            expected_status=AuditStatus.PASSED,
            expected_overcharge=0.0,
            expected_violation_types=[],
        ))

        # 2. Subtle Rate Creep ($80 -> $85, $80 -> $95, $55 -> $60, $120 -> $135)
        cases.append(TestCase(
            id="TC-03",
            description="Sneaky rate creep: Senior DevOps billed at $85/hr (+$5/hr across 100 hrs = $500)",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-03",
                payment_terms="Net 30",
                line_items=[InvoiceLineItem(description="Senior DevOps Engineer - Cloud Architecture", quantity=100, unit_price=85, total_price=8500)],
                subtotal=8500, tax_amount=0, total_amount=8500,
            ),
            expected_status=AuditStatus.FLAGGED,
            expected_overcharge=500.0,
            expected_violation_types=[DiscrepancyType.RATE_MISMATCH],
        ))

        cases.append(TestCase(
            id="TC-04",
            description="Aggressive rate creep: Senior DevOps billed at $95/hr (+$15/hr across 80 hrs = $1200)",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-04",
                payment_terms="Net 30",
                line_items=[InvoiceLineItem(description="Senior DevOps Engineer", quantity=80, unit_price=95, total_price=7600)],
                subtotal=7600, tax_amount=0, total_amount=7600,
            ),
            expected_status=AuditStatus.FLAGGED,
            expected_overcharge=1200.0,
            expected_violation_types=[DiscrepancyType.RATE_MISMATCH],
        ))

        cases.append(TestCase(
            id="TC-05",
            description="QA rate inflation: QA Engineer billed at $65/hr instead of $55/hr (+$10/hr across 80 hrs = $800)",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-05",
                payment_terms="Net 30",
                line_items=[InvoiceLineItem(description="QA Automation Engineer - Test Suites", quantity=80, unit_price=65, total_price=5200)],
                subtotal=5200, tax_amount=0, total_amount=5200,
            ),
            expected_status=AuditStatus.FLAGGED,
            expected_overcharge=800.0,
            expected_violation_types=[DiscrepancyType.RATE_MISMATCH],
        ))

        # 3. Phantom / Unapproved Surcharges
        cases.append(TestCase(
            id="TC-06",
            description="Unapproved fee: Emergency On-Call Surcharge ($350)",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-06",
                payment_terms="Net 30",
                line_items=[
                    InvoiceLineItem(description="Senior DevOps Engineer", quantity=40, unit_price=80, total_price=3200),
                    InvoiceLineItem(description="Emergency On-Call Platform Support Surcharge", quantity=1, unit_price=350, total_price=350),
                ],
                subtotal=3550, tax_amount=0, total_amount=3550,
            ),
            expected_status=AuditStatus.FLAGGED,
            expected_overcharge=350.0,
            expected_violation_types=[DiscrepancyType.UNAPPROVED_FEE],
        ))

        cases.append(TestCase(
            id="TC-07",
            description="Unapproved administrative fee: Tooling & License Fee ($490)",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-07",
                payment_terms="Net 30",
                line_items=[
                    InvoiceLineItem(description="Cloud Solutions Architect", quantity=20, unit_price=120, total_price=2400),
                    InvoiceLineItem(description="Proprietary CI/CD Tooling Maintenance Fee", quantity=1, unit_price=490, total_price=490),
                ],
                subtotal=2890, tax_amount=0, total_amount=2890,
            ),
            expected_status=AuditStatus.FLAGGED,
            expected_overcharge=490.0,
            expected_violation_types=[DiscrepancyType.UNAPPROVED_FEE],
        ))

        # 4. Scope & Monthly Hour Cap Violations
        cases.append(TestCase(
            id="TC-08",
            description="Scope cap violation: Senior DevOps billed for 190 hrs (Cap is 160 hrs, 30 excess hrs @ $80 = $2400)",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-08",
                payment_terms="Net 30",
                line_items=[InvoiceLineItem(description="Senior DevOps Engineer", quantity=190, unit_price=80, total_price=15200)],
                subtotal=15200, tax_amount=0, total_amount=15200,
            ),
            expected_status=AuditStatus.FLAGGED,
            expected_overcharge=2400.0,
            expected_violation_types=[DiscrepancyType.HOURS_EXCEEDED],
        ))

        cases.append(TestCase(
            id="TC-09",
            description="Architect cap violation: 100 hrs billed (Cap is 80 hrs, 20 excess hrs @ $120 = $2400)",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-09",
                payment_terms="Net 30",
                line_items=[InvoiceLineItem(description="Cloud Solutions Architect", quantity=100, unit_price=120, total_price=12000)],
                subtotal=12000, tax_amount=0, total_amount=12000,
            ),
            expected_status=AuditStatus.FLAGGED,
            expected_overcharge=2400.0,
            expected_violation_types=[DiscrepancyType.HOURS_EXCEEDED],
        ))

        # 5. Payment Term Mismatches (Terms altered unilaterally by vendor)
        cases.append(TestCase(
            id="TC-10",
            description="Payment term mismatch: Due in Net 15 instead of contracted Net 30",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-10",
                payment_terms="Net 15",
                line_items=[InvoiceLineItem(description="Senior DevOps Engineer", quantity=40, unit_price=80, total_price=3200)],
                subtotal=3200, tax_amount=0, total_amount=3200,
            ),
            expected_status=AuditStatus.FLAGGED,
            expected_overcharge=0.0,
            expected_violation_types=[DiscrepancyType.PAYMENT_TERM_MISMATCH],
        ))

        # 6. Compound Violations (Rate Creep + Unapproved Surcharge + Term Mismatch)
        cases.append(TestCase(
            id="TC-11",
            description="Triple compound violation: Rate Mismatch ($1200) + Unapproved Surcharge ($350) + Net 15",
            invoice=ParsedInvoice(
                vendor_name=self.contract.vendor_name,
                invoice_number="INV-EVAL-11",
                payment_terms="Net 15",
                line_items=[
                    InvoiceLineItem(description="Senior DevOps Engineer", quantity=80, unit_price=95, total_price=7600),
                    InvoiceLineItem(description="Platform Maintenance & On-Call Emergency Surcharge", quantity=1, unit_price=350, total_price=350),
                ],
                subtotal=7950, tax_amount=0, total_amount=7950,
            ),
            expected_status=AuditStatus.FLAGGED,
            expected_overcharge=1550.0,
            expected_violation_types=[DiscrepancyType.RATE_MISMATCH, DiscrepancyType.UNAPPROVED_FEE, DiscrepancyType.PAYMENT_TERM_MISMATCH],
        ))

        # 7. Additional Stress & Boundary Test Cases
        for i in range(12, 21):
            is_valid = (i % 2 == 0)
            if is_valid:
                cases.append(TestCase(
                    id=f"TC-{i:02d}",
                    description=f"Boundary Test {i}: Compliant random distribution QA hours ({40 + i * 2} hrs)",
                    invoice=ParsedInvoice(
                        vendor_name=self.contract.vendor_name,
                        invoice_number=f"INV-EVAL-{i:02d}",
                        payment_terms="Net 30",
                        line_items=[InvoiceLineItem(description="QA Automation Engineer", quantity=40 + i, unit_price=55, total_price=(40 + i) * 55)],
                        subtotal=(40 + i) * 55, tax_amount=0, total_amount=(40 + i) * 55,
                    ),
                    expected_status=AuditStatus.PASSED,
                    expected_overcharge=0.0,
                    expected_violation_types=[],
                ))
            else:
                overcharge = (i * 20.0)
                cases.append(TestCase(
                    id=f"TC-{i:02d}",
                    description=f"Boundary Test {i}: Unapproved cloud egress charge (+${overcharge:.2f})",
                    invoice=ParsedInvoice(
                        vendor_name=self.contract.vendor_name,
                        invoice_number=f"INV-EVAL-{i:02d}",
                        payment_terms="Net 30",
                        line_items=[
                            InvoiceLineItem(description="Senior DevOps Engineer", quantity=20, unit_price=80, total_price=1600),
                            InvoiceLineItem(description="Unapproved Cloud Egress Transit Surcharge", quantity=1, unit_price=overcharge, total_price=overcharge),
                        ],
                        subtotal=1600 + overcharge, tax_amount=0, total_amount=1600 + overcharge,
                    ),
                    expected_status=AuditStatus.FLAGGED,
                    expected_overcharge=overcharge,
                    expected_violation_types=[DiscrepancyType.UNAPPROVED_FEE],
                ))

        return cases

    def run_evaluations(self) -> Dict[str, Any]:
        suite = self.build_test_suite()
        total_cases = len(suite)

        true_positives = 0
        false_positives = 0
        true_negatives = 0
        false_negatives = 0
        dollar_deltas = []
        latencies = []

        print(f"\n=======================================================")
        print(f"⚡ RUNNING COMPLIANCE BENCHMARK EVALUATIONS ({total_cases} CASES)")
        print(f"=======================================================\n")

        for test in suite:
            start_t = time.perf_counter()
            report = self.engine.audit_invoice(test.invoice, self.contract)
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            latencies.append(elapsed_ms)

            is_predicted_flag = (report.status == AuditStatus.FLAGGED)
            is_actual_flag = (test.expected_status == AuditStatus.FLAGGED)

            if is_predicted_flag and is_actual_flag:
                true_positives += 1
            elif is_predicted_flag and not is_actual_flag:
                false_positives += 1
            elif not is_predicted_flag and not is_actual_flag:
                true_negatives += 1
            else:
                false_negatives += 1

            overcharge_delta = abs(report.total_overcharge - test.expected_overcharge)
            dollar_deltas.append(overcharge_delta)

            status_icon = "✓" if (is_predicted_flag == is_actual_flag and overcharge_delta < 0.01) else "✗"
            print(f"[{status_icon}] {test.id}: {test.description[:55]}... | {elapsed_ms:.1f}ms | Pred: {report.status.value} (Diff: ${overcharge_delta:.2f})")

        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 1.0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 1.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        fpr = false_positives / (false_positives + true_negatives) if (false_positives + true_negatives) > 0 else 0.0
        avg_latency = sum(latencies) / len(latencies)

        results = {
            "total_cases": total_cases,
            "true_positives": true_positives,
            "false_positives": false_positives,
            "true_negatives": true_negatives,
            "false_negatives": false_negatives,
            "precision": round(precision * 100, 2),
            "recall": round(recall * 100, 2),
            "f1_score": round(f1 * 100, 2),
            "false_positive_rate": round(fpr * 100, 2),
            "financial_delta_accuracy": round((1.0 - (sum(dollar_deltas) / max(1, sum(t.expected_overcharge for t in suite)))) * 100, 2),
            "avg_latency_ms": round(avg_latency, 2),
        }

        print("\n-------------------------------------------------------")
        print("📊 BENCHMARK EVALUATION SUMMARY")
        print("-------------------------------------------------------")
        print(f"• Precision:               {results['precision']}%")
        print(f"• Recall:                  {results['recall']}%")
        print(f"• F1-Score:                {results['f1_score']}%")
        print(f"• False-Positive Rate:     {results['false_positive_rate']}%")
        print(f"• Financial Accuracy:      {results['financial_delta_accuracy']}%")
        print(f"• Average Audit Latency:   {results['avg_latency_ms']} ms")
        print("=======================================================\n")

        return results


if __name__ == "__main__":
    from src.database.session import SessionLocal
    from src.database.models import ContractRecord

    db = SessionLocal()
    contract_rec = db.query(ContractRecord).filter_by(contract_ref="MSA-2025-CS01").first()

    if not contract_rec:
        print("[ERROR] Contract not found. Run seed script first.")
        sys.exit(1)

    # Convert ORM to Pydantic
    contract = VendorContract(
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

    evaluator = ComplianceEvaluator(contract)
    evaluator.run_evaluations()
