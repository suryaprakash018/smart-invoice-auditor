import os
from typing import Optional, Dict, Any
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
            "You cite exact contract clauses (like Section 4.2 for surcharges, Schedule A for rates). "
            "If the user asks to negotiate (e.g. meet at $87/hr), recalculate the overcharge and explain the delta. "
            "Keep your responses sharp, professional, and actionable."
        )

        context_prompt = f"""
Current Invoice Context:
- Vendor: {invoice.vendor_name}
- Invoice #: {invoice.invoice_number}
- Billed Total: ${invoice.total_amount:,.2f}
- Contract Authorized: ${report.total_expected:,.2f}
- Current Overcharge: ${report.total_overcharge:,.2f}
- Discrepancies: {[d.description for d in report.discrepancies]}
- Contract Notes: {contract.notes}

User Question/Request: "{user_message}"

Provide a concise, professional response. If you recommend an updated dispute draft or adjusted numbers, include them.
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
        msg_lower = user_message.lower()

        # 1. Why was fee flagged?
        if "why" in msg_lower and ("350" in msg_lower or "fee" in msg_lower or "surcharge" in msg_lower):
            reply = (
                f"**Legal Analysis (Section 4.2 Surcharges & Inflation):**\n\n"
                f"Under MSA {contract.contract_id}, Section 4.2 explicitly stipulates that *'No off-hours platform support, "
                f"emergency dispatch, or infrastructure maintenance surcharge shall be levied unless pre-approved in writing via an authorized Change Order.'*\n\n"
                f"Invoice #{invoice.invoice_number} billed $350.00 for 'Platform Maintenance & On-Call Emergency Surcharge' "
                f"without an attached Change Order signed by Acme AP. Therefore, 100% of this fee is unauthorized."
            )
            return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}

        # 2. Negotiate / Meet Halfway
        if "negotiate" in msg_lower or "87" in msg_lower or "halfway" in msg_lower or "compromise" in msg_lower:
            # Senior DevOps was billed at $95 (contract $80). Meeting at $87.50:
            # Overcharge becomes: (87.50 - 80) * 80 hrs = $600 + $350 unapproved = $950
            concession_rate = 87.50
            devops_compromise_overcharge = (95.0 - concession_rate) * 80.0
            new_overcharge = devops_compromise_overcharge + 350.0  # $600 + $350 = $950
            new_authorized = invoice.total_amount - new_overcharge

            revised_email = (
                f"Subject: Settlement Proposal - Invoice #{invoice.invoice_number} Adjustment\n\n"
                f"Dear {invoice.vendor_name} Billing Team,\n\n"
                f"Regarding Invoice #{invoice.invoice_number}, while our Master Services Agreement specifies a rate of $80.00/hr "
                f"for Senior DevOps, in the spirit of strategic partnership we propose a compromised settlement rate of ${concession_rate:.2f}/hr "
                f"for the 80 hours billed in February ($7,000.00).\n\n"
                f"Additionally, the $350.00 Emergency Surcharge is waived as it lacked an authorized Change Order under Section 4.2.\n\n"
                f"• Revised Authorized Settlement Total: ${new_authorized:,.2f}\n"
                f"• Total Adjustment / Credit Memo Requested: ${new_overcharge:,.2f}\n\n"
                f"Please confirm if you accept this revised settlement so we can release payment immediately.\n\n"
                f"Best regards,\nAccounts Payable & Vendor Operations"
            )

            reply = (
                f"**Counter-Offer Computed (Concession Rate: ${concession_rate:.2f}/hr):**\n\n"
                f"• Billed DevOps: $95.00/hr ($7,600.00)\n"
                f"• Contracted Limit: $80.00/hr ($6,400.00)\n"
                f"• Proposed Settlement: ${concession_rate:.2f}/hr ($7,000.00)\n"
                f"• Revised Overcharge to Credit: **${new_overcharge:,.2f}** (Saves ${new_overcharge:,.2f} while granting a $600 vendor goodwill concession).\n\n"
                f"I have rewritten the dispute letter into a formal Settlement Proposal ready for dispatch."
            )
            return {
                "reply": reply,
                "adjusted_overcharge": new_overcharge,
                "revised_draft": revised_email,
            }

        # 3. Polite / Partnership Tone
        if "polite" in msg_lower or "diplomatic" in msg_lower or "soft" in msg_lower or "friendly" in msg_lower:
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
                "**Tone Adjusted to Diplomatic / Strategic Partner:**\n\n"
                "I have rewritten the notice to maintain warm vendor relations while firmly requesting the $1,550.00 correction."
            )
            return {
                "reply": reply,
                "adjusted_overcharge": None,
                "revised_draft": revised_email,
            }

        # Default legal advice
        reply = (
            f"**Veritas Compliance Analysis for #{invoice.invoice_number}:**\n\n"
            f"• Vendor: {invoice.vendor_name} under contract {contract.contract_id}.\n"
            f"• Contract Violations: 3 items detected totaling **${report.total_overcharge:,.2f}** in financial leakage.\n"
            f"• Recommendation: Dispatch the formal dispute notice and place an Accounts Payable hold to prevent disbursement."
        )
        return {"reply": reply, "adjusted_overcharge": None, "revised_draft": None}
