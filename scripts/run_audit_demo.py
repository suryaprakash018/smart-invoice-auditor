import os
import sys
import json

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.models import VendorContract, AuditStatus
from src.extractor import InvoiceExtractor
from src.audit_engine import ContractAuditEngine

console = Console()


def run_demo():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    contract_path = os.path.join(base_dir, "data", "contracts", "cloudscale_msa.json")
    valid_pdf = os.path.join(base_dir, "data", "sample_invoices", "invoice_valid.pdf")
    overcharged_pdf = os.path.join(base_dir, "data", "sample_invoices", "invoice_overcharged.pdf")

    # Load Contract
    with open(contract_path, "r") as f:
        contract_data = json.load(f)
    contract = VendorContract(**contract_data)

    console.print(Panel(
        f"[bold cyan]Vendor Contract Loaded:[/bold cyan] {contract.vendor_name} ({contract.contract_id})\n"
        f"Payment Terms: {contract.payment_terms}\n"
        f"Agreed Rates: {', '.join([f'{r.role_or_item} (${r.agreed_rate}/{r.unit})' for r in contract.rates])}",
        title="[bold green]Contract Knowledge Store[/bold green]",
        border_style="green"
    ))

    extractor = InvoiceExtractor()
    engine = ContractAuditEngine()

    test_invoices = [
        ("TEST 1: Valid Contract-Compliant Invoice", valid_pdf),
        ("TEST 2: Non-Compliant Overcharged Invoice", overcharged_pdf),
    ]

    for test_name, pdf_path in test_invoices:
        console.rule(f"[bold yellow]{test_name}[/bold yellow]")
        console.print(f"Ingesting & extracting: [italic]{os.path.basename(pdf_path)}[/italic]...")

        invoice = extractor.extract_from_pdf(pdf_path)
        report = engine.audit_invoice(invoice, contract)

        # Build Summary Table
        table = Table(title=f"Audit Result for Invoice #{report.invoice_number}")
        table.add_column("Field", style="bold")
        table.add_column("Value")

        status_color = "green" if report.status == AuditStatus.PASSED else "red"
        table.add_row("Status", f"[{status_color} bold]{report.status.value}[/{status_color} bold]")
        table.add_row("Vendor Name", report.vendor_name)
        table.add_row("Billed Total", f"${report.total_billed:,.2f}")
        table.add_row("Expected Total", f"${report.total_expected:,.2f}")
        table.add_row("Total Overcharge", f"[{status_color}]${report.total_overcharge:,.2f}[/{status_color}]")

        console.print(table)

        if report.discrepancies:
            disc_table = Table(title="[bold red]Detected Discrepancies[/bold red]", border_style="red")
            disc_table.add_column("Type", style="bold")
            disc_table.add_column("Description")
            disc_table.add_column("Billed")
            disc_table.add_column("Authorized")
            disc_table.add_column("Overcharge", style="red bold")

            for d in report.discrepancies:
                disc_table.add_row(
                    d.type.value,
                    d.description,
                    f"${d.billed_amount:.2f}",
                    f"${d.expected_amount:.2f}",
                    f"+${d.overcharge:.2f}" if d.overcharge > 0 else "$0.00",
                )
            console.print(disc_table)

        if report.suggested_dispute_email:
            console.print(Panel(
                report.suggested_dispute_email,
                title="[bold blue]Auto-Drafted Vendor Dispute Notice[/bold blue]",
                border_style="blue"
            ))


if __name__ == "__main__":
    run_demo()
