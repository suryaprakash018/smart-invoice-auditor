import os
import sys
import asyncio
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.models import ParsedInvoice, AuditReport
from src.extractor import InvoiceExtractor
from src.audit_engine import ContractAuditEngine
from src.database.session import SessionLocal
from src.database.models import ContractRecord
from src.server import _get_contract_pydantic_from_db, _persist_audit_to_db


class TelegramAuditBridge:
    """
    Telegram Bot bridge that listens for uploaded PDF invoices,
    audits them asynchronously against relational contracts,
    and returns rich interactive Telegram cards with one-tap action buttons.
    """

    def __init__(self, bot_token: Optional[str] = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.extractor = InvoiceExtractor()
        self.engine = ContractAuditEngine()

    def process_incoming_pdf(self, pdf_file_path: str) -> dict:
        """
        Simulates or executes processing of an incoming PDF from mobile Telegram.
        """
        db = SessionLocal()
        try:
            parsed_invoice = self.extractor.extract_from_pdf(pdf_file_path)
            contract = _get_contract_pydantic_from_db(db, parsed_invoice.vendor_name)
            if not contract:
                raise ValueError("No governing contract found for vendor.")

            report = self.engine.audit_invoice(parsed_invoice, contract)
            audit_id = _persist_audit_to_db(db, parsed_invoice, report, pdf_file_path)

            telegram_msg = self._format_telegram_message(parsed_invoice, report)

            return {
                "audit_id": audit_id,
                "status": report.status.value,
                "overcharge": report.total_overcharge,
                "formatted_telegram_markdown": telegram_msg,
                "inline_keyboard": [
                    [{"text": "✉️ Dispatch Dispute & AP Hold", "callback_data": f"DISPUTE_{report.invoice_number}"}],
                    [{"text": "⚠️ Grant Exception", "callback_data": f"APPROVE_{report.invoice_number}"}],
                    [{"text": "❌ Reject Invoice", "callback_data": f"REJECT_{report.invoice_number}"}],
                ]
            }
        finally:
            db.close()

    def _format_telegram_message(self, invoice: ParsedInvoice, report: AuditReport) -> str:
        status_icon = "🚨" if report.status.value == "FLAGGED" else "✅"
        lines = [
            f"{status_icon} *VERITAS AP AUDIT ALERT*",
            f"━━━━━━━━━━━━━━━━━━━",
            f"*Vendor:* {invoice.vendor_name}",
            f"*Invoice:* `#{invoice.invoice_number}`",
            f"*Billed Total:* `${invoice.total_amount:,.2f}`",
            f"*Authorized Total:* `${report.total_expected:,.2f}`",
            f"*Overcharge Arrested:* `+${report.total_overcharge:,.2f}`",
            f"━━━━━━━━━━━━━━━━━━━",
        ]

        if report.discrepancies:
            lines.append("*Violations Detected:*")
            for d in report.discrepancies:
                lines.append(f"• `{d.type.value}`: {d.description}")
        else:
            lines.append("✓ 100% Compliant to Master Services Agreement.")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━",
            "_Tap an action button below to commit sign-off into the immutable ledger:_"
        ])

        return "\n".join(lines)


if __name__ == "__main__":
    sample_pdf = os.path.join(BASE_DIR, "data", "sample_invoices", "invoice_overcharged.pdf")
    bridge = TelegramAuditBridge()
    result = bridge.process_incoming_pdf(sample_pdf)
    print("\n[TELEGRAM MOBILE ALERT FORMAT]:\n")
    print(result["formatted_telegram_markdown"])
