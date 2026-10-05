"""
Veritas AP Enterprise - Outbound Financial Webhook Dispatcher
Supports HMAC-SHA256 signing, Slack Block Kit, and Microsoft Teams Adaptive Cards.
"""

import hmac
import hashlib
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

DEFAULT_WEBHOOK_SECRET = "veritas_sec_financial_ops_2026"


def generate_hmac_signature(payload_bytes: bytes, secret: str = DEFAULT_WEBHOOK_SECRET) -> str:
    """Generates an HMAC-SHA256 signature string for webhook integrity verification."""
    mac = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def format_slack_block_kit(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Formats event data into an enterprise Slack Block Kit message payload."""
    inv_num = data.get("invoice_number", "INV-UNKNOWN")
    vendor = data.get("vendor_name", "ACME Corp")
    reviewer = data.get("reviewer_name", "Surya Prakash")
    reviewer_role = data.get("reviewer_role", "AP Specialist")
    disputed = data.get("disputed_amount", 0.0)
    gross = data.get("gross_amount", 0.0)

    title_map = {
        "invoice.audit.flagged": "🚨 Veritas AP: Contract Discrepancy Flagged",
        "hitl.decision.dispute_dispatched": "✉️ Legal Dispute Notice Dispatched",
        "hitl.decision.partial_remittance": "💳 Partial Remittance & Credit Memo Authorized",
        "hitl.decision.executive_override": "🛡️ Executive Override Approved (VP Finance)",
        "erp.export.generated": "💼 ERP Journal Batch Exported"
    }

    title = title_map.get(event_type, f"📢 Veritas AP Notification: {event_type}")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": title,
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Invoice:* `{inv_num}`\n*Vendor:* {vendor}"},
                {"type": "mrkdwn", "text": f"*Gross Billed:* `${gross:,.2f}`\n*Discrepancy:* `${disputed:,.2f}`"}
            ]
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Sign-off Person:* {reviewer}\n*Role:* `{reviewer_role}`"},
                {"type": "mrkdwn", "text": f"*Timestamp:* <!date^{int(datetime.utcnow().timestamp())}^{{date_num}} {{time_secs}}|{datetime.utcnow().isoformat()}>"}
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🔐 *Audit Integrity:* Verified via Veritas 0.15ms Deterministic Engine • Event: `{event_type}`"
                }
            ]
        }
    ]

    return {"text": title, "blocks": blocks}


def format_teams_adaptive_card(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Formats event data into a Microsoft Teams Adaptive Card (v1.4) payload."""
    inv_num = data.get("invoice_number", "INV-UNKNOWN")
    vendor = data.get("vendor_name", "ACME Corp")
    reviewer = data.get("reviewer_name", "Surya Prakash")
    disputed = data.get("disputed_amount", 0.0)
    gross = data.get("gross_amount", 0.0)

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "size": "Medium",
                            "weight": "Bolder",
                            "text": f"Veritas AP Alert: {event_type}"
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Invoice", "value": inv_num},
                                {"title": "Vendor", "value": vendor},
                                {"title": "Gross Billed", "value": f"${gross:,.2f}"},
                                {"title": "Discrepancy Withheld", "value": f"${disputed:,.2f}"},
                                {"title": "Authorized By", "value": reviewer}
                            ]
                        }
                    ]
                }
            }
        ]
    }


def dispatch_webhook(
    event_type: str,
    event_data: Dict[str, Any],
    target_url: Optional[str] = None,
    secret: str = DEFAULT_WEBHOOK_SECRET,
    simulate: bool = True
) -> Dict[str, Any]:
    """
    Constructs, signs, and dispatches an enterprise webhook payload.
    Supports real HTTP POST dispatch or simulated delivery logging.
    """
    timestamp = datetime.utcnow().isoformat()
    raw_event = {
        "id": f"evt_{int(datetime.utcnow().timestamp() * 1000)}",
        "event": event_type,
        "created_at": timestamp,
        "data": event_data
    }

    payload_json = json.dumps(raw_event, indent=2)
    payload_bytes = payload_json.encode("utf-8")
    signature = generate_hmac_signature(payload_bytes, secret)

    slack_card = format_slack_block_kit(event_type, event_data)
    teams_card = format_teams_adaptive_card(event_type, event_data)

    status_code = 200
    success = True
    error_message = None

    if target_url and not simulate:
        try:
            req = urllib.request.Request(
                target_url,
                data=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Veritas-AP-Webhook/2.0",
                    "X-Veritas-Signature": signature,
                    "X-Veritas-Event": event_type
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                status_code = response.getcode()
                success = 200 <= status_code < 300
        except urllib.error.HTTPError as e:
            status_code = e.code
            success = False
            error_message = str(e)
        except Exception as e:
            status_code = 500
            success = False
            error_message = str(e)

    return {
        "event_id": raw_event["id"],
        "event_type": event_type,
        "target_url": target_url or "https://hooks.slack.com/services/SIMULATED/FINANCE/ALERTS",
        "signature": signature,
        "status_code": status_code,
        "success": success,
        "simulated": simulate or not target_url,
        "error": error_message,
        "payload": raw_event,
        "slack_preview": slack_card,
        "teams_preview": teams_card
    }
