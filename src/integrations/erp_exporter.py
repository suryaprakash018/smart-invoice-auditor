"""
Veritas AP Enterprise - Multi-Standard ERP & Accounting Export Engine
Supports SAP S/4HANA (FI Document), Oracle NetSuite (Vendor Bill/Credit), and QuickBooks Online (Journal/IIF).
"""

import csv
import io
import json
from datetime import datetime
from typing import Dict, Any, Tuple, Optional


def export_to_sap(
    invoice_data: Dict[str, Any],
    audit_data: Dict[str, Any],
    decision_data: Optional[Dict[str, Any]] = None,
    format_type: str = "csv"
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Exports invoice audit resolution to SAP S/4HANA Financial Accounting (FI-AP) format.
    Generates balanced Document Header and Line Items (Posting Key 31: Vendor Credit, 40: Expense Debit).
    """
    inv_num = invoice_data.get("invoice_number", "INV-UNKNOWN")
    vendor_name = invoice_data.get("vendor_name", "ACME Corporation")
    currency = invoice_data.get("currency", "USD")
    total_billed = float(invoice_data.get("total_amount", 0.0))
    
    # Calculate authorized and disputed amounts
    disputed_amount = float(audit_data.get("total_overcharge", 0.0))
    if decision_data and decision_data.get("action") == "APPROVE_OVERCHARGE":
        authorized_payment = total_billed
        disputed_amount = 0.0
    elif decision_data and decision_data.get("disputed_amount") is not None:
        disputed_amount = float(decision_data["disputed_amount"])
        authorized_payment = total_billed - disputed_amount
    else:
        authorized_payment = float(audit_data.get("total_expected", total_billed - disputed_amount))

    today_str = datetime.utcnow().strftime("%Y%m%d")
    filename = f"SAP_S4HANA_FI_{inv_num}_{today_str}.{format_type.lower()}"

    summary = {
        "erp_system": "SAP S/4HANA",
        "document_type": "KR (Vendor Invoice)",
        "company_code": "1000",
        "currency": currency,
        "gross_billed": total_billed,
        "authorized_payable": round(authorized_payment, 2),
        "disputed_escrow": round(disputed_amount, 2),
        "is_balanced": True,
        "posting_date": today_str
    }

    if format_type.lower() == "json":
        sap_payload = {
            "d": {
                "AccountingDocumentType": "KR",
                "CompanyCode": "1000",
                "FiscalYear": datetime.utcnow().strftime("%Y"),
                "DocumentDate": invoice_data.get("invoice_date", today_str).replace("-", ""),
                "PostingDate": today_str,
                "DocumentReferenceID": inv_num,
                "DocumentHeaderText": f"Veritas Audit Verified: {vendor_name}",
                "to_Item": [
                    {
                        "DebitCreditCode": "S",  # Debit
                        "FinancialAccountType": "S",
                        "GeneralLedgerAccount": "600100",  # IT Consulting Expense
                        "AmountInTransactionCurrency": f"{total_billed:.2f}",
                        "CostCenter": "CC_IT_ENG",
                        "DocumentItemText": f"Gross IT Consulting Services - {inv_num}"
                    },
                    {
                        "DebitCreditCode": "H",  # Credit
                        "FinancialAccountType": "K",  # Vendor
                        "Supplier": "VEND_90214",
                        "AmountInTransactionCurrency": f"-{authorized_payment:.2f}",
                        "PaymentTerms": invoice_data.get("payment_terms", "NT30"),
                        "DocumentItemText": f"Authorized Net AP Remittance - {inv_num}"
                    }
                ]
            }
        }
        if disputed_amount > 0:
            sap_payload["d"]["to_Item"].append({
                "DebitCreditCode": "H",  # Credit to Escrow / Special GL
                "FinancialAccountType": "K",
                "Supplier": "VEND_90214",
                "SpecialGLCode": "E",  # Escrow Hold
                "AmountInTransactionCurrency": f"-{disputed_amount:.2f}",
                "DocumentItemText": f"Disputed Contract Breach Withheld - {inv_num}"
            })
        return filename, json.dumps(sap_payload, indent=2), summary

    # Default CSV Format for SAP Data Services / Batch Input
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "RecordType", "DocType", "CompanyCode", "PostingDate", "DocDate", 
        "Currency", "RefDoc", "PostingKey", "Account", "Amount", 
        "CostCenter", "TaxCode", "ItemText"
    ])
    
    # 1. Expense Debit (Key 40)
    writer.writerow([
        "ITEM", "KR", "1000", today_str, invoice_data.get("invoice_date", today_str),
        currency, inv_num, "40", "600100", f"{total_billed:.2f}",
        "CC_IT_ENG", "V0", f"Billed Services - {inv_num}"
    ])
    # 2. Vendor AP Credit (Key 31)
    writer.writerow([
        "ITEM", "KR", "1000", today_str, invoice_data.get("invoice_date", today_str),
        currency, inv_num, "31", "VEND_90214", f"-{authorized_payment:.2f}",
        "CC_IT_ENG", "V0", f"Authorized Remittance - {inv_num}"
    ])
    # 3. Disputed Credit Hold (Key 39 if overcharged)
    if disputed_amount > 0:
        writer.writerow([
            "ITEM", "KR", "1000", today_str, invoice_data.get("invoice_date", today_str),
            currency, inv_num, "39", "VEND_90214", f"-{disputed_amount:.2f}",
            "CC_IT_ENG", "V0", f"Escrow Hold Contract Discrepancy - {inv_num}"
        ])

    return filename, output.getvalue(), summary


def export_to_netsuite(
    invoice_data: Dict[str, Any],
    audit_data: Dict[str, Any],
    decision_data: Optional[Dict[str, Any]] = None,
    format_type: str = "csv"
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Exports to Oracle NetSuite Vendor Bill & Bill Credit import CSV / REST SuiteScript format.
    """
    inv_num = invoice_data.get("invoice_number", "INV-UNKNOWN")
    vendor_name = invoice_data.get("vendor_name", "ACME Corporation")
    total_billed = float(invoice_data.get("total_amount", 0.0))
    disputed_amount = float(audit_data.get("total_overcharge", 0.0))

    if decision_data and decision_data.get("action") == "APPROVE_OVERCHARGE":
        authorized_payment = total_billed
        disputed_amount = 0.0
    elif decision_data and decision_data.get("disputed_amount") is not None:
        disputed_amount = float(decision_data["disputed_amount"])
        authorized_payment = total_billed - disputed_amount
    else:
        authorized_payment = float(audit_data.get("total_expected", total_billed - disputed_amount))

    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    filename = f"NetSuite_VendorBill_{inv_num}_{datetime.utcnow().strftime('%Y%m%d')}.{format_type.lower()}"

    summary = {
        "erp_system": "Oracle NetSuite",
        "entity": vendor_name,
        "transaction_type": "Vendor Bill + Bill Credit",
        "net_payable": round(authorized_payment, 2),
        "credit_memo_amount": round(disputed_amount, 2),
        "approval_status": "Approved for Partial Remittance" if disputed_amount > 0 else "Approved"
    }

    if format_type.lower() == "json":
        ns_payload = {
            "recordType": "vendorBill",
            "entity": {"name": vendor_name, "id": "10492"},
            "tranId": inv_num,
            "tranDate": today_str,
            "dueDate": invoice_data.get("due_date", today_str),
            "terms": {"name": invoice_data.get("payment_terms", "Net 30")},
            "approvalStatus": {"id": "2", "refName": "Approved"},
            "memo": f"Veritas Audited: {len(audit_data.get('discrepancies', []))} discrepancy exceptions resolved",
            "itemList": {
                "item": [
                    {
                        "item": {"name": "Software Engineering Services"},
                        "rate": authorized_payment,
                        "amount": authorized_payment,
                        "description": f"Verified Compliant Remittance for {inv_num}"
                    }
                ]
            }
        }
        if disputed_amount > 0:
            ns_payload["creditMemoReference"] = {
                "recordType": "vendorCredit",
                "entity": {"name": vendor_name, "id": "10492"},
                "appliedTo": inv_num,
                "amount": disputed_amount,
                "memo": f"Disputed Contract Overcharge Withheld - Clause §3.1 / §4.2"
            }
        return filename, json.dumps(ns_payload, indent=2), summary

    # NetSuite Standard Import CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "TransactionType", "Entity", "Date", "DueDate", "ReferenceNo", 
        "ExpenseAccount", "Amount", "ApprovalStatus", "Memo"
    ])
    
    # Authorized Bill
    writer.writerow([
        "Vendor Bill", vendor_name, today_str, invoice_data.get("due_date", today_str),
        inv_num, "6100 - Professional Services", f"{authorized_payment:.2f}",
        "Approved", f"Veritas AP Cleared Payment - {inv_num}"
    ])
    
    # Credit Memo if disputed
    if disputed_amount > 0:
        writer.writerow([
            "Vendor Credit", vendor_name, today_str, today_str,
            f"CM-{inv_num}", "6100 - Professional Services", f"{disputed_amount:.2f}",
            "Applied", f"Withheld Disputed Surcharge/Overcharge - {inv_num}"
        ])

    return filename, output.getvalue(), summary


def export_to_quickbooks(
    invoice_data: Dict[str, Any],
    audit_data: Dict[str, Any],
    decision_data: Optional[Dict[str, Any]] = None,
    format_type: str = "csv"
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Exports to QuickBooks Online (QBO) Journal Entry / Bill CSV.
    """
    inv_num = invoice_data.get("invoice_number", "INV-UNKNOWN")
    vendor_name = invoice_data.get("vendor_name", "ACME Corporation")
    total_billed = float(invoice_data.get("total_amount", 0.0))
    disputed_amount = float(audit_data.get("total_overcharge", 0.0))

    if decision_data and decision_data.get("action") == "APPROVE_OVERCHARGE":
        authorized_payment = total_billed
        disputed_amount = 0.0
    elif decision_data and decision_data.get("disputed_amount") is not None:
        disputed_amount = float(decision_data["disputed_amount"])
        authorized_payment = total_billed - disputed_amount
    else:
        authorized_payment = float(audit_data.get("total_expected", total_billed - disputed_amount))

    today_str = datetime.utcnow().strftime("%m/%d/%Y")
    filename = f"QuickBooks_Journal_{inv_num}_{datetime.utcnow().strftime('%Y%m%d')}.{format_type.lower()}"

    summary = {
        "erp_system": "QuickBooks Online",
        "vendor": vendor_name,
        "entry_type": "Journal Entry / Bill",
        "debit_expense": round(total_billed, 2),
        "credit_ap": round(authorized_payment, 2),
        "credit_escrow": round(disputed_amount, 2),
        "is_balanced": True
    }

    if format_type.lower() == "json":
        qbo_payload = {
            "TxnDate": datetime.utcnow().strftime("%Y-%m-%d"),
            "DocNumber": inv_num,
            "PrivateNote": f"Veritas Automated AP Audit - {vendor_name}",
            "Line": [
                {
                    "Description": f"Verified Consulting Services {inv_num}",
                    "Amount": total_billed,
                    "DetailType": "JournalEntryLineDetail",
                    "JournalEntryLineDetail": {
                        "PostingType": "Debit",
                        "AccountRef": {"value": "6001", "name": "Contractor Expenses"},
                        "Entity": {"Type": "Vendor", "EntityRef": {"name": vendor_name}}
                    }
                },
                {
                    "Description": f"Net Authorized Payable {inv_num}",
                    "Amount": authorized_payment,
                    "DetailType": "JournalEntryLineDetail",
                    "JournalEntryLineDetail": {
                        "PostingType": "Credit",
                        "AccountRef": {"value": "2000", "name": "Accounts Payable"},
                        "Entity": {"Type": "Vendor", "EntityRef": {"name": vendor_name}}
                    }
                }
            ]
        }
        if disputed_amount > 0:
            qbo_payload["Line"].append({
                "Description": f"Disputed Contract Hold {inv_num}",
                "Amount": disputed_amount,
                "DetailType": "JournalEntryLineDetail",
                "JournalEntryLineDetail": {
                    "PostingType": "Credit",
                    "AccountRef": {"value": "2050", "name": "Disputed Vendor Escrow"},
                    "Entity": {"Type": "Vendor", "EntityRef": {"name": vendor_name}}
                }
            })
        return filename, json.dumps(qbo_payload, indent=2), summary

    # CSV Format for QuickBooks Online Batch Import
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "JournalNo", "Date", "Account", "Debits", "Credits", 
        "Description", "Name", "Currency"
    ])
    
    # Debit Expense
    writer.writerow([
        inv_num, today_str, "Contractor Expenses", f"{total_billed:.2f}", "",
        f"IT Consulting Billed Services - {inv_num}", vendor_name, "USD"
    ])
    # Credit AP (Authorized)
    writer.writerow([
        inv_num, today_str, "Accounts Payable", "", f"{authorized_payment:.2f}",
        f"Authorized Remittance - {inv_num}", vendor_name, "USD"
    ])
    # Credit Escrow (Disputed)
    if disputed_amount > 0:
        writer.writerow([
            inv_num, today_str, "Disputed Vendor Escrow", "", f"{disputed_amount:.2f}",
            f"Overcharge Escrow Hold - {inv_num}", vendor_name, "USD"
        ])

    return filename, output.getvalue(), summary


def generate_erp_export(
    invoice_data: Dict[str, Any],
    audit_data: Dict[str, Any],
    decision_data: Optional[Dict[str, Any]] = None,
    erp_system: str = "SAP",
    format_type: str = "csv"
) -> Dict[str, Any]:
    """
    Unified entry point for ERP exports.
    """
    sys_upper = erp_system.upper()
    if "SAP" in sys_upper:
        filename, content, summary = export_to_sap(invoice_data, audit_data, decision_data, format_type)
    elif "NETSUITE" in sys_upper:
        filename, content, summary = export_to_netsuite(invoice_data, audit_data, decision_data, format_type)
    elif "QUICKBOOKS" in sys_upper or "QBO" in sys_upper:
        filename, content, summary = export_to_quickbooks(invoice_data, audit_data, decision_data, format_type)
    else:
        # Default to SAP S/4HANA
        filename, content, summary = export_to_sap(invoice_data, audit_data, decision_data, format_type)

    return {
        "success": True,
        "erp_system": summary["erp_system"],
        "format": format_type.upper(),
        "filename": filename,
        "content": content,
        "summary": summary
    }
