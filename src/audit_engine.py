from typing import List, Optional
from difflib import SequenceMatcher
from src.models import (
    ParsedInvoice,
    VendorContract,
    AuditReport,
    AuditStatus,
    DiscrepancyItem,
    DiscrepancyType,
    ContractRate,
)


class ContractAuditEngine:
    def __init__(self, similarity_threshold: float = 0.6):
        self.similarity_threshold = similarity_threshold

    def audit_invoice(self, invoice: ParsedInvoice, contract: VendorContract) -> AuditReport:
        discrepancies: List[DiscrepancyItem] = []
        total_expected = 0.0

        # 1. Audit Line Items against Contract Rate Cards
        for item in invoice.line_items:
            matched_rate = self._find_matching_rate(item.description, contract.rates)

            if matched_rate:
                expected_line_total = item.quantity * matched_rate.agreed_rate
                total_expected += expected_line_total

                # Rate Mismatch Check
                if item.unit_price > matched_rate.agreed_rate:
                    unit_diff = item.unit_price - matched_rate.agreed_rate
                    overcharge = round(unit_diff * item.quantity, 2)
                    discrepancies.append(
                        DiscrepancyItem(
                            type=DiscrepancyType.RATE_MISMATCH,
                            description=(
                                f"Billed rate ${item.unit_price:.2f}/{matched_rate.unit} exceeds "
                                f"contracted rate ${matched_rate.agreed_rate:.2f}/{matched_rate.unit} "
                                f"for '{matched_rate.role_or_item}'"
                            ),
                            billed_amount=round(item.unit_price, 2),
                            expected_amount=round(matched_rate.agreed_rate, 2),
                            overcharge=overcharge,
                        )
                    )

                # Cap / Max Hours Exceeded Check
                if matched_rate.max_monthly_units and item.quantity > matched_rate.max_monthly_units:
                    excess_units = item.quantity - matched_rate.max_monthly_units
                    overcharge = round(excess_units * matched_rate.agreed_rate, 2)
                    discrepancies.append(
                        DiscrepancyItem(
                            type=DiscrepancyType.HOURS_EXCEEDED,
                            description=(
                                f"Billed units ({item.quantity} {matched_rate.unit}s) exceed monthly contracted cap of "
                                f"{matched_rate.max_monthly_units} {matched_rate.unit}s by {excess_units} units."
                            ),
                            billed_amount=round(item.quantity, 2),
                            expected_amount=round(matched_rate.max_monthly_units, 2),
                            overcharge=overcharge,
                        )
                    )

                # Math check on line item
                calculated_item_total = round(item.quantity * item.unit_price, 2)
                if abs(calculated_item_total - item.total_price) > 0.05:
                    math_diff = round(item.total_price - calculated_item_total, 2)
                    discrepancies.append(
                        DiscrepancyItem(
                            type=DiscrepancyType.MATH_CALCULATION_ERROR,
                            description=(
                                f"Math discrepancy on line '{item.description}': "
                                f"{item.quantity} x ${item.unit_price:.2f} = ${calculated_item_total:.2f}, "
                                f"but billed as ${item.total_price:.2f}."
                            ),
                            billed_amount=item.total_price,
                            expected_amount=calculated_item_total,
                            overcharge=math_diff,
                        )
                    )
            else:
                # Line item not found in contract rates - check allowed extra fees
                is_allowed_fee = any(
                    fee.lower() in item.description.lower() for fee in contract.allowed_extra_fees
                )
                if not is_allowed_fee:
                    discrepancies.append(
                        DiscrepancyItem(
                            type=DiscrepancyType.UNAPPROVED_FEE,
                            description=(
                                f"Unapproved charge: '{item.description}' is not included in contract "
                                f"rate card or permitted extra fees."
                            ),
                            billed_amount=item.total_price,
                            expected_amount=0.0,
                            overcharge=item.total_price,
                        )
                    )

        # 2. Audit Payment Terms
        if invoice.payment_terms and contract.payment_terms:
            if invoice.payment_terms.strip().lower() != contract.payment_terms.strip().lower():
                discrepancies.append(
                    DiscrepancyItem(
                        type=DiscrepancyType.PAYMENT_TERM_MISMATCH,
                        description=(
                            f"Payment terms mismatch: Invoice specifies '{invoice.payment_terms}', "
                            f"whereas contract '{contract.contract_id}' stipulates '{contract.payment_terms}'."
                        ),
                        billed_amount=0.0,
                        expected_amount=0.0,
                        overcharge=0.0,
                    )
                )

        # 3. Overall Totals and Overcharge
        total_overcharge = round(sum(d.overcharge for d in discrepancies), 2)
        total_expected = round(invoice.total_amount - total_overcharge, 2)

        if total_overcharge > 0 or discrepancies:
            status = AuditStatus.FLAGGED
            dispute_email = self._draft_dispute_email(invoice, contract, discrepancies, total_expected, total_overcharge)
        else:
            status = AuditStatus.PASSED
            dispute_email = None

        return AuditReport(
            invoice_number=invoice.invoice_number,
            vendor_name=invoice.vendor_name,
            status=status,
            total_billed=invoice.total_amount,
            total_expected=total_expected,
            total_overcharge=total_overcharge,
            discrepancies=discrepancies,
            suggested_dispute_email=dispute_email,
        )

    def _find_matching_rate(self, item_description: str, rates: List[ContractRate]) -> Optional[ContractRate]:
        item_lower = item_description.lower()
        best_match = None
        highest_score = 0.0

        for rate in rates:
            role_lower = rate.role_or_item.lower()
            if role_lower in item_lower:
                return rate  # Substring exact match

            score = SequenceMatcher(None, role_lower, item_lower).ratio()
            if score > highest_score and score >= self.similarity_threshold:
                highest_score = score
                best_match = rate

        return best_match

    def _draft_dispute_email(
        self,
        invoice: ParsedInvoice,
        contract: VendorContract,
        discrepancies: List[DiscrepancyItem],
        expected_total: float,
        overcharge: float,
    ) -> str:
        lines = [
            f"Subject: Discrepancy Notice & Adjustment Request - Invoice #{invoice.invoice_number}",
            "",
            f"Dear {invoice.vendor_name} Billing Team,",
            "",
            f"Thank you for submitting Invoice #{invoice.invoice_number} dated {invoice.invoice_date or 'recently'}.",
            f"During our automated compliance review against Master Services Agreement ({contract.contract_id}), "
            f"we identified discrepancies totaling ${overcharge:,.2f}:",
            "",
        ]

        for idx, d in enumerate(discrepancies, 1):
            if d.overcharge > 0:
                lines.append(f"{idx}. {d.description} (Discrepancy: +${d.overcharge:,.2f})")
            else:
                lines.append(f"{idx}. {d.description}")

        lines.extend([
            "",
            f"Based on the terms outlined in Contract {contract.contract_id}:",
            f"• Billed Total: ${invoice.total_amount:,.2f}",
            f"• Contract Authorized Total: ${expected_total:,.2f}",
            f"• Net Overcharge to be Credited/Adjusted: ${overcharge:,.2f}",
            "",
            f"Please reissue an adjusted invoice reflecting the authorized amount of ${expected_total:,.2f}, "
            f"or issue a credit memo for ${overcharge:,.2f}. If you have any supporting change orders, please attach them.",
            "",
            "Best regards,",
            "Accounts Payable & Vendor Operations",
            "Acme Enterprises Inc.",
        ])

        return "\n".join(lines)
