import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def build_invoice_pdf(filename, invoice_data):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    story = []
    styles = getSampleStyleSheet()

    # Custom Styles
    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#1E293B"),
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748B"),
    )
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#0F172A"),
        fontName="Helvetica-Bold",
    )

    # Header / Title
    story.append(Paragraph(invoice_data["vendor_name"], title_style))
    story.append(Paragraph(invoice_data.get("vendor_address", "100 Tech Park Way, Suite 400<br/>San Francisco, CA 94107"), subtitle_style))
    story.append(Spacer(1, 20))

    # Meta Info (Invoice #, Date, Terms, Bill To)
    meta_table_data = [
        [
            Paragraph("<b>BILLED TO:</b><br/>Acme Enterprises Inc.<br/>Accounts Payable<br/>ap@acme-enterprises.com", subtitle_style),
            Paragraph(
                f"<b>INVOICE #:</b> {invoice_data['invoice_number']}<br/>"
                f"<b>DATE:</b> {invoice_data['invoice_date']}<br/>"
                f"<b>DUE DATE:</b> {invoice_data['due_date']}<br/>"
                f"<b>PAYMENT TERMS:</b> {invoice_data['payment_terms']}",
                subtitle_style
            )
        ]
    ]
    meta_table = Table(meta_table_data, colWidths=[280, 240])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 25))

    # Line Items Table
    table_data = [
        [
            Paragraph("<b>Description</b>", header_style),
            Paragraph("<b>Qty / Hrs</b>", header_style),
            Paragraph("<b>Unit Rate ($)</b>", header_style),
            Paragraph("<b>Total ($)</b>", header_style),
        ]
    ]

    for item in invoice_data["items"]:
        table_data.append([
            Paragraph(item["description"], subtitle_style),
            Paragraph(str(item["quantity"]), subtitle_style),
            Paragraph(f"${item['unit_price']:.2f}", subtitle_style),
            Paragraph(f"${item['total_price']:.2f}", subtitle_style),
        ])

    # Totals rows
    table_data.append(["", "", Paragraph("<b>Subtotal:</b>", subtitle_style), Paragraph(f"<b>${invoice_data['subtotal']:.2f}</b>", subtitle_style)])
    if invoice_data.get("tax", 0) > 0:
        table_data.append(["", "", Paragraph("<b>Tax:</b>", subtitle_style), Paragraph(f"<b>${invoice_data['tax']:.2f}</b>", subtitle_style)])
    table_data.append(["", "", Paragraph("<b>TOTAL DUE:</b>", header_style), Paragraph(f"<b>${invoice_data['total']:.2f}</b>", header_style)])

    line_items_table = Table(table_data, colWidths=[270, 75, 85, 90])
    line_items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor("#CBD5E1")),
        ('LINEBELOW', (0, 1), (-1, len(invoice_data["items"])), 0.5, colors.HexColor("#E2E8F0")),
        ('LINEBELOW', (2, -1), (-1, -1), 1.5, colors.HexColor("#0F172A")),
    ]))

    story.append(line_items_table)
    story.append(Spacer(1, 30))

    # Footer note
    story.append(Paragraph("<b>Payment Instructions:</b> Please remit payment via ACH or Wire to Silicon Valley Bank, Routing #121000358, Account #883920194.", subtitle_style))

    doc.build(story)
    print(f"[OK] Generated: {filename}")


if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data", "sample_invoices")
    os.makedirs(out_dir, exist_ok=True)

    # 1. Perfectly Compliant Invoice
    valid_invoice = {
        "vendor_name": "CloudScale Innovations",
        "invoice_number": "INV-2025-081",
        "invoice_date": "2025-02-01",
        "due_date": "2025-03-03",
        "payment_terms": "Net 30",
        "items": [
            {
                "description": "Senior DevOps Engineer - Infrastructure Migration & CI/CD",
                "quantity": 80.0,
                "unit_price": 80.0,
                "total_price": 6400.0,
            }
        ],
        "subtotal": 6400.0,
        "tax": 0.0,
        "total": 6400.0,
    }

    # 2. Overcharged / Non-compliant Invoice
    # Discrepancy 1: Billed $95/hr instead of $80/hr (overcharge: $1,200)
    # Discrepancy 2: Unapproved "Platform Maintenance Surcharge" ($350)
    # Discrepancy 3: Due in 15 days (Net 15) instead of contracted Net 30
    overcharged_invoice = {
        "vendor_name": "CloudScale Innovations",
        "invoice_number": "INV-2025-094",
        "invoice_date": "2025-02-15",
        "due_date": "2025-03-02",
        "payment_terms": "Net 15",
        "items": [
            {
                "description": "Senior DevOps Engineer - Cloud Architecture & Reliability",
                "quantity": 80.0,
                "unit_price": 95.0,  # Contract says $80!
                "total_price": 7600.0,
            },
            {
                "description": "Platform Maintenance & On-Call Emergency Surcharge",
                "quantity": 1.0,
                "unit_price": 350.0,  # Unapproved fee!
                "total_price": 350.0,
            },
        ],
        "subtotal": 7950.0,
        "tax": 0.0,
        "total": 7950.0,
    }

    build_invoice_pdf(os.path.join(out_dir, "invoice_valid.pdf"), valid_invoice)
    build_invoice_pdf(os.path.join(out_dir, "invoice_overcharged.pdf"), overcharged_invoice)
