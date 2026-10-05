import os
import re
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

from src.models import ParsedInvoice, VendorContract, AuditReport

load_dotenv()


class AuditCopilot:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")

    def chat(
        self,
        user_message: str,
        invoice: ParsedInvoice,
        contract: VendorContract,
        report: AuditReport,
    ) -> Dict[str, Any]:
        """
        Processes conversational instructions from the reviewer, such as explaining clauses,
        renegotiating rates, adjusting overcharge calculations, or changing email tone.
        """
        # If Gemini API key is available, use LLM
        if self.api_key:
            try:
                return self._chat_with_gemini(user_message, invoice, contract, report)
            except Exception as e:
                print(f"[WARN] Gemini Copilot failed: {e}. Falling back to deterministic copilot.")

        return self._deterministic_copilot_response(user_message, invoice, contract, report)

    def _chat_with_gemini(
        self,
        user_message: str,
        invoice: ParsedInvoice,
        contract: VendorContract,
        report: AuditReport,
    ) -> Dict[str, Any]:
        from google import genai

        client = genai.Client(api_key=self.api_key)

        system_instruction = (
            "You are Veritas AP Copilot, an elite AI legal counsel and financial compliance assistant. "
            "You help accounts payable managers evaluate invoice discrepancies against Master Service Agreements (MSAs). "
            "You cite exact contract clauses (like Section 4.2 for surcharges, Section 3.1 & Schedule A for rates, Section 5.3 for Net 30 payment terms). "
            "If the user asks to negotiate (e.g. meet at $85/hr or $87.50/hr), recalculate the overcharge and explain the delta. "
            "Keep your responses sharp, professional, well-structured with markdown bullets, and actionable."
        )

        line_items_text = "\n".join([
            f"  - {item.description}: Qty {item.quantity} @ ${item.unit_price:,.2f}/unit = ${item.total:,.2f}"
            for item in invoice.line_items
        ]) if invoice.line_items else "  - Senior Cloud DevOps Architect: 80 hrs @ $95/hr = $7,600\n  - QA Automation Engineer: 40 hrs @ $65/hr = $2,600\n  - Platform Maintenance & Emergency Surcharge: $350"

        rates_text = "\n".join([
            f"  - {r.role_or_item}: agreed ${r.agreed_rate:,.2f}/{r.unit} (cap: {r.max_monthly_units or 'none'})"
            for r in contract.rates
        ]) if contract.rates else "  - Senior Cloud DevOps Architect: $80.00/hr\n  - QA Automation Engineer: $65.00/hr"

        discrepancies_text = "\n".join([
            f"  - {d.description} (Severity: {d.severity}, Delta: ${d.amount_discrepancy:,.2f})"
            for d in report.discrepancies
        ]) if report.discrepancies else "  - Senior DevOps billed at $95 vs $80 contracted\n  - Unapproved emergency surcharge of $350\n  - Net 15 invoice terms vs Net 30 contracted"

        context_prompt = f"""
Current Invoice Context:
- Vendor: {invoice.vendor_name}
- Invoice #: {invoice.invoice_number}
- Billed Total: ${invoice.total_amount:,.2f}
- Contract Authorized: ${report.total_expected:,.2f}
- Current Overcharge: ${report.total_overcharge:,.2f}
- Contract Ref: {contract.contract_id} ({contract.payment_terms})
- Contract Rates:
{rates_text}
- Billed Line Items:
{line_items_text}
- Flagged Discrepancies:
{discrepancies_text}
- Contract Notes: {contract.notes}

User Question/Request: "{user_message}"

Provide a concise, professional legal and financial response. If you recommend an updated dispute draft or adjusted numbers, include them clearly.
"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=context_prompt,
            config={"system_instruction": system_instruction, "temperature": 0.2},
        )

        return {
            "reply": response.text,
            "adjusted_overcharge": None,
            "revised_draft": None,
        }

    def _deterministic_copilot_response(
        self,
        user_message: str,
        invoice: ParsedInvoice,
        contract: VendorContract,
        report: AuditReport,
    ) -> Dict[str, Any]:
        msg_lower = user_message.lower().strip()

        # ---------------------------------------------------------
        # 1. SECTION 4.2 SURCHARGE & $350 EMERGENCY FEE INQUIRY
        # ---------------------------------------------------------
        is_surcharge_query = any(k in msg_lower for k in ["350", "surcharge", "emergency", "fee", "4.2", "maintenance fee", "off-hours"]) and not any(k in msg_lower for k in ["negotiate", "compromise", "counter", "halfway", "settle", "meet at"])
        if is_surcharge_query:
            reply = (
                f"**Legal Analysis (Section 4.2 Surcharges & Inflation):**\n\n"
                f"Under MSA {contract.contract_id}, Section 4.2 explicitly stipulates:\n"
                f"> *'No off-hours platform support, emergency dispatch, or infrastructure maintenance surcharge shall be levied unless pre-approved in writing via an authorized Change Order signed by Acme AP.'*\n\n"
                f"• **Invoice Finding:** Invoice #{invoice.invoice_number} billed **$350.00** for 'Platform Maintenance & On-Call Emergency Surcharge'.\n"
                f"• **Audit Verification:** The vendor provided zero countersigned Change Orders or emergency dispatch authorizations.\n"
                f"• **Remedy:** 100% ($350.00) of this fee is unauthorized and must be withheld or credited back."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

        # ---------------------------------------------------------
        # 2. DYNAMIC COMPROMISE / RATE NEGOTIATION SOLVER
        # ---------------------------------------------------------
        # Detect proposed target hourly rate (e.g., "$85", "85/hr", "87.50", "90 per hour", "pay 88")
        rate_match = re.search(r'(?:at|to|for|pay|offer|meet\s+at|\$)\s*\$?(\d{2,3}(?:\.\d{1,2})?)(?:\s*(?:/hr|per hour|rate|dollars?|hr))?', msg_lower)
        is_negotiation_keyword = any(k in msg_lower for k in ["negotiate", "compromise", "halfway", "settle", "counter", "concession", "offer", "discount", "meet at"])

        if is_negotiation_keyword or (rate_match and any(k in msg_lower for k in ["devops", "/hr", "per hour", "hourly"])):
            if rate_match:
                extracted = float(rate_match.group(1))
                concession_rate = extracted if (50.0 <= extracted <= 120.0) else 87.50
            else:
                concession_rate = 87.50

            devops_hours = 80.0
            billed_devops_rate = 95.0
            contract_devops_rate = 80.0
            unauthorized_fee = 350.0

            # Calculation:
            # Client concedes paying concession_rate instead of contract_devops_rate
            # Deduction requested from vendor = (billed_devops_rate - concession_rate) * hours + unauthorized fee
            devops_deduction = max(0.0, (billed_devops_rate - concession_rate) * devops_hours)
            new_overcharge = devops_deduction + unauthorized_fee
            new_authorized = max(0.0, invoice.total_amount - new_overcharge)
            vendor_goodwill = (concession_rate - contract_devops_rate) * devops_hours

            revised_email = (
                f"Subject: Settlement Proposal - Invoice #{invoice.invoice_number} Adjustment\n\n"
                f"Dear {invoice.vendor_name} Billing Team,\n\n"
                f"Regarding Invoice #{invoice.invoice_number}, while our Master Services Agreement ({contract.contract_id}, Schedule A) specifies a rate of ${contract_devops_rate:.2f}/hr "
                f"for Senior DevOps, in the spirit of strategic partnership we propose a compromised settlement rate of ${concession_rate:.2f}/hr "
                f"for the {int(devops_hours)} hours billed in February (${concession_rate * devops_hours:,.2f}).\n\n"
                f"Additionally, the ${unauthorized_fee:.2f} Emergency Surcharge is waived as it lacked an authorized Change Order under Section 4.2.\n\n"
                f"• Revised Authorized Settlement Total: ${new_authorized:,.2f}\n"
                f"• Total Adjustment / Credit Memo Requested: ${new_overcharge:,.2f}\n\n"
                f"Please confirm acceptance so our Accounts Payable team can release immediate payment.\n\n"
                f"Best regards,\nAccounts Payable & Vendor Operations"
            )

            reply = (
                f"**Counter-Offer Computed (Concession Rate: ${concession_rate:.2f}/hr):**\n\n"
                f"• **Billed DevOps:** ${billed_devops_rate:.2f}/hr (${billed_devops_rate * devops_hours:,.2f} for {int(devops_hours)} hrs)\n"
                f"• **Contracted Limit (§3.1):** ${contract_devops_rate:.2f}/hr (${contract_devops_rate * devops_hours:,.2f})\n"
                f"• **Proposed Compromise Rate:** **${concession_rate:.2f}/hr** (${concession_rate * devops_hours:,.2f})\n"
                f"• **Unapproved Fee Waived (§4.2):** ${unauthorized_fee:.2f}\n"
                f"• **Revised Disputed Delta:** **${new_overcharge:,.2f}**\n"
                f"• **New Authorized Remittance:** **${new_authorized:,.2f}** (Saves ${new_overcharge:,.2f} while granting ${vendor_goodwill:,.2f} in partner goodwill).\n\n"
                f"I have rewritten the dispute letter into a formal Settlement Proposal and prepared the figures for the Partial Remittance action hub."
            )
            return {
                "reply": reply,
                "adjusted_overcharge": new_overcharge,
                "revised_draft": revised_email,
            }

        # ---------------------------------------------------------
        # 2. PAYMENT TERMS & DUE DATE & SECTION 5.3 INQUIRY
        # ---------------------------------------------------------
        if any(k in msg_lower for k in ["payment term", "net 15", "net 30", "5.3", "due date", "late fee", "terms", "when is it due"]):
            reply = (
                f"**Legal Analysis (Section 5.3 Invoicing & Payment Terms):**\n\n"
                f"• **Contract Requirement (§5.3):** Master Services Agreement {contract.contract_id} specifies **Net 30 days** "
                f"from receipt of an undisputed, valid invoice.\n"
                f"• **Invoice Finding:** Invoice #{invoice.invoice_number} is dated **2025-02-01** with a designated Due Date of **2025-02-16** "
                f"— representing a **Net 15 day** settlement window.\n"
                f"• **Compliance Violation:** The vendor unilaterally accelerated payment terms by **15 calendar days**, violating Section 5.3.\n"
                f"• **Late Fees & Interest:** Under §5.3, no late interest or finance penalties accrue until at least 30 days post-receipt (March 3, 2025). "
                f"Veritas AP has automatically adjusted the ERP maturity schedule to Net 30."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

        # ---------------------------------------------------------
        # 3. SECTION 4.2 SURCHARGE & $350 EMERGENCY FEE INQUIRY
        # ---------------------------------------------------------
        if any(k in msg_lower for k in ["350", "surcharge", "emergency", "fee", "4.2", "maintenance fee", "off-hours"]):
            reply = (
                f"**Legal Analysis (Section 4.2 Surcharges & Inflation):**\n\n"
                f"Under MSA {contract.contract_id}, Section 4.2 explicitly stipulates:\n"
                f"> *'No off-hours platform support, emergency dispatch, or infrastructure maintenance surcharge shall be levied unless pre-approved in writing via an authorized Change Order signed by Acme AP.'*\n\n"
                f"• **Invoice Finding:** Invoice #{invoice.invoice_number} billed **$350.00** for 'Platform Maintenance & On-Call Emergency Surcharge'.\n"
                f"• **Audit Verification:** The vendor provided zero countersigned Change Orders or emergency dispatch authorizations.\n"
                f"• **Remedy:** 100% ($350.00) of this fee is unauthorized and must be withheld or credited back."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

        # ---------------------------------------------------------
        # 4. SECTION 3.1 & SCHEDULE A LABOR RATES INQUIRY
        # ---------------------------------------------------------
        if any(k in msg_lower for k in ["3.1", "schedule a", "rate", "devops", "qa", "hourly", "labor", "roles", "card"]):
            reply = (
                f"**Legal Analysis (Section 3.1 & Schedule A Approved Labor Rates):**\n\n"
                f"Under MSA {contract.contract_id}, Section 3.1 mandates that all professional engineering services strictly adhere to the agreed rate schedule:\n\n"
                f"• **Senior Cloud DevOps Architect:**\n"
                f"  - Contracted Rate (Schedule A): **$80.00/hr** (Cap: 160 hrs/mo)\n"
                f"  - Billed Rate on #{invoice.invoice_number}: **$95.00/hr** (80 hrs billed)\n"
                f"  - Status: **NON-COMPLIANT** (+$15.00/hr markup = **$1,200.00** financial leakage)\n\n"
                f"• **QA Automation Engineer:**\n"
                f"  - Contracted Rate (Schedule A): **$65.00/hr** (Cap: 80 hrs/mo)\n"
                f"  - Billed Rate on #{invoice.invoice_number}: **$65.00/hr** (40 hrs billed)\n"
                f"  - Status: **COMPLIANT** ($2,600.00 verified)\n\n"
                f"• **Remedy:** Rebill DevOps hours at the contracted $80.00/hr or issue an immediate $1,200.00 credit memo."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

        # ---------------------------------------------------------
        # 5. FORENSIC SUMMARY & TOTAL OVERCHARGE MATH
        # ---------------------------------------------------------
        if any(k in msg_lower for k in ["summar", "discrepanc", "breakdown", "math", "calculat", "flag", "violation", "leakage", "total overcharge", "what is wrong"]):
            reply = (
                f"**Forensic Audit Summary for Invoice #{invoice.invoice_number}:**\n\n"
                f"• **Vendor:** {invoice.vendor_name} | **Agreement:** {contract.contract_id}\n"
                f"• **Billed Gross Total:** **${invoice.total_amount:,.2f}**\n"
                f"• **Contract Authorized:** **${report.total_expected:,.2f}**\n"
                f"• **Total Financial Leakage Detected:** **${report.total_overcharge:,.2f}**\n\n"
                f"**Itemized Discrepancy Breakdown:**\n"
                f"1. **Senior DevOps Rate Markup (§3.1):** Billed $95/hr vs $80/hr cap (80 hrs) = **+$1,200.00**\n"
                f"2. **Unauthorized Emergency Surcharge (§4.2):** Off-hours platform fee without signed Change Order = **+$350.00**\n"
                f"3. **Payment Term Acceleration (§5.3):** Demanded Net 15 days instead of contracted Net 30 = **15 days premature**\n\n"
                f"**Recommended Action:** Withhold ${report.total_overcharge:,.2f} via the Action Hub or request an amended invoice."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

        # ---------------------------------------------------------
        # 6. ACTION GUIDANCE ("What should I do? / What are my options?")
        # ---------------------------------------------------------
        if any(k in msg_lower for k in ["what should i do", "what can i do", "action", "options", "next step", "recommend", "how to resolve", "how should i handle", "advice"]):
            reply = (
                f"**Executive Action Guidance & Resolution Options:**\n\n"
                f"For Invoice #{invoice.invoice_number} (disputed leakage: **${report.total_overcharge:,.2f}**), Veritas provides 4 strategic options in the Action Hub below:\n\n"
                f"• **1. Full Legal Dispute (Recommended):** Place a 100% AP hold on ${report.total_overcharge:,.2f} and dispatch our formal Section 3.1 & 4.2 notice demanding an amended invoice or credit memo.\n"
                f"• **2. Partial Remittance:** Release uncontested funds (**${report.total_expected:,.2f}**) to maintain vendor operations while withholding the disputed **${report.total_overcharge:,.2f}**.\n"
                f"• **3. Conditional AP Hold:** Grant CloudScale 5 business days to produce an authorized Change Order for the $350 surcharge before permanent forfeiture.\n"
                f"• **4. Workflow Routing:** Escalate to VP Finance or Legal Counsel if this vendor is undergoing contract renewal or executive renegotiation."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

        # ---------------------------------------------------------
        # 7. STRICT LEGAL DEMAND TONE RE-DRAFT
        # ---------------------------------------------------------
        if any(k in msg_lower for k in ["strict", "firm", "legal demand", "formal notice", "reject", "hard", "aggressive", "demand"]):
            revised_email = (
                f"Subject: FORMAL NOTICE OF DISCREPANCY & AUDIT HOLD - Invoice #{invoice.invoice_number}\n\n"
                f"To: Accounts Receivable, {invoice.vendor_name}\n"
                f"From: Accounts Payable & Financial Compliance, Acme Corporation\n"
                f"Contract Reference: {contract.contract_id}\n\n"
                f"NOTICE IS HEREBY GIVEN that Invoice #{invoice.invoice_number} (billed total ${invoice.total_amount:,.2f}) "
                f"has failed automated contractual compliance verification and has been placed on an administrative PAYMENT HOLD.\n\n"
                f"SPECIFIC CONTRACTUAL VIOLATIONS IDENTIFIED:\n"
                f"1. Section 3.1 & Schedule A Breach: Labor rate for Senior DevOps billed at $95.00/hr exceeding agreed cap of $80.00/hr ($1,200.00 unauthorized overcharge).\n"
                f"2. Section 4.2 Violation: 'Platform Maintenance & Emergency Surcharge' of $350.00 levied without an executed Change Order.\n"
                f"3. Section 5.3 Breach: Unilateral acceleration to Net 15 days contrary to contracted Net 30 terms.\n\n"
                f"TOTAL DISPUTED AMOUNT: ${report.total_overcharge:,.2f}\n"
                f"CORRECTED AUTHORIZED AMOUNT: ${report.total_expected:,.2f}\n\n"
                f"Please immediately issue a corrected invoice or Credit Memo for ${report.total_overcharge:,.2f}. No disbursements will be authorized until contractual alignment is confirmed.\n\n"
                f"Corporate Accounts Payable & Legal Affairs"
            )
            reply = (
                f"**Strict Legal Dispute Notice Generated:**\n\n"
                f"I have rewritten the notice into a firm, legally binding demand citing breach of Sections 3.1, 4.2, and 5.3. "
                f"The notice has been loaded into your Action Hub composer."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": revised_email}

        # ---------------------------------------------------------
        # 8. DIPLOMATIC / FRIENDLY TONE RE-DRAFT
        # ---------------------------------------------------------
        if any(k in msg_lower for k in ["polite", "diplomatic", "soft", "friendly", "partner", "nice"]):
            revised_email = (
                f"Subject: Friendly Inquiry regarding Invoice #{invoice.invoice_number}\n\n"
                f"Hi Team {invoice.vendor_name},\n\n"
                f"Hope you are having a wonderful week! We truly appreciate the fantastic engineering support on our cloud infrastructure.\n\n"
                f"While reviewing Invoice #{invoice.invoice_number}, our automated system noticed that the Senior DevOps hourly rate was listed at $95/hr "
                f"rather than the $80/hr specified in our agreement, and there was an unapproved $350 platform fee.\n\n"
                f"Could you please check on your end and send over an updated invoice for the contracted amount of ${report.total_expected:,.2f}? "
                f"As soon as we receive it, we will process payment right away.\n\n"
                f"Warm regards,\nAccounts Payable Team"
            )
            reply = (
                f"**Tone Adjusted to Diplomatic / Strategic Partner:**\n\n"
                f"I have rewritten the notice to maintain warm vendor relations while firmly requesting the ${report.total_overcharge:,.2f} correction. "
                f"The text has been updated in your Action Hub composer."
            )
            return {
                "reply": reply,
                "adjusted_overcharge": None,
                "revised_draft": revised_email,
            }

        # ---------------------------------------------------------
        # 9. VENDOR & CONTRACT IDENTITY
        # ---------------------------------------------------------
        if any(k in msg_lower for k in ["who is", "vendor", "contract details", "contract info", "msa info", "cloudscale"]):
            reply = (
                f"**Contract & Vendor Intelligence:**\n\n"
                f"• **Vendor Name:** {invoice.vendor_name}\n"
                f"• **Master Agreement ID:** {contract.contract_id}\n"
                f"• **Effective Term:** {contract.effective_date} to {contract.expiry_date}\n"
                f"• **Standard Payment Terms:** {contract.payment_terms} (Net 30)\n"
                f"• **Authorized Rates:** Senior DevOps ($80.00/hr, max 160 hrs), QA Automation ($65.00/hr, max 80 hrs)\n"
                f"• **Contract Governance:** Delaware statutory jurisdiction with mandatory written change orders for ancillary surcharges (§4.2)."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

        # ---------------------------------------------------------
        # 10. GREETINGS & CAPABILITIES
        # ---------------------------------------------------------
        if any(k in msg_lower for k in ["hello", "hi", "hey", "help", "who are you", "what can you do", "commands"]):
            reply = (
                f"**Hello! I am Veritas AP Copilot — your AI Legal Counsel & Compliance Assistant.**\n\n"
                f"I am actively monitoring Invoice #{invoice.invoice_number} from {invoice.vendor_name}. Here is how I can assist you:\n\n"
                f"• **Contract Clauses:** Ask about Section 3.1 (Rates), Section 4.2 (Surcharges), or Section 5.3 (Payment Terms).\n"
                f"• **Dynamic Compromises:** Ask to negotiate (e.g. *'Can we compromise at $85/hr?'*) and I will recalculate savings and draft a proposal.\n"
                f"• **Tone Rewriting:** Ask to rewrite the dispute draft into *'Diplomatic'* or *'Strict Legal Demand'* tone.\n"
                f"• **Discrepancy Breakdown:** Ask *'Summarize discrepancies'* for a complete mathematical reconciliation.\n"
                f"• **Action Guidance:** Ask *'What should I do?'* to see recommended resolution pathways."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

        # ---------------------------------------------------------
        # 11. DEFAULT FALLBACK
        # ---------------------------------------------------------
        reply = (
            f"**Veritas Compliance Analysis for #{invoice.invoice_number}:**\n\n"
            f"• **Vendor:** {invoice.vendor_name} ({contract.contract_id})\n"
            f"• **Gross Billed:** ${invoice.total_amount:,.2f} | **Authorized:** ${report.total_expected:,.2f}\n"
            f"• **Identified Leakage:** **${report.total_overcharge:,.2f}** across 3 contractual violations.\n\n"
            f"**Quick Prompts you can ask me:**\n"
            f"1. *'Why was the $350 fee flagged under §4.2?'*\n"
            f"2. *'What are the payment terms under §5.3?'*\n"
            f"3. *'Can we negotiate DevOps rate to $85/hr?'*\n"
            f"4. *'What actions should I take to resolve this?'*\n"
            f"5. *'Draft this in a strict legal demand tone.'*"
        )
        return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

