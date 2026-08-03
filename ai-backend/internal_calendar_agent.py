"""Prototype-only internal calendar backed by CSV; no external calendar account is used."""
import csv
from datetime import datetime, timezone
from pathlib import Path

from messaging import send_email, update_lead
from lead_status_agent import update_target as update_sales_status

BASE_DIR = Path(__file__).resolve().parent
CALENDAR = BASE_DIR / "data" / "internal_calendar.csv"
FIELDS = ["event_id", "target", "scheduled_for", "title", "recipient", "subject", "body", "in_reply_to", "references", "status", "created_at", "sent_at"]


def schedule_email(target: str, scheduled_for: str, recipient: str, subject: str, body: str, in_reply_to: str = "", references: str = "") -> dict:
    """Save one scheduled, thread-aware email. Duplicate target/time events are ignored."""
    event_id = f"{target}|{scheduled_for}|{recipient}".lower()
    rows = []
    if CALENDAR.exists():
        with CALENDAR.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    existing = next((row for row in rows if row.get("event_id") == event_id and row.get("status") == "scheduled"), None)
    if existing:
        return existing
    event = {
        "event_id": event_id, "target": target, "scheduled_for": scheduled_for,
        "title": f"Follow up with {target}", "recipient": recipient, "subject": subject, "body": body,
        "in_reply_to": in_reply_to, "references": references, "status": "scheduled",
        "created_at": datetime.now(timezone.utc).isoformat(), "sent_at": "",
    }
    CALENDAR.parent.mkdir(exist_ok=True)
    with CALENDAR.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows + [event])
    update_lead(target, message_status="Meeting follow-up scheduled", next_action=f"Internal calendar: send scheduled email at {scheduled_for}.")
    return event


def run_due_events() -> dict:
    """Send due calendar emails through the existing Gmail allowlist and record results."""
    if not CALENDAR.exists():
        return {"checked": 0, "sent": 0}
    with CALENDAR.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    now = datetime.now(timezone.utc)
    sent = 0
    for row in rows:
        if row.get("status") != "scheduled":
            continue
        try:
            due = datetime.fromisoformat(row["scheduled_for"])
            due = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
        except ValueError:
            row["status"] = "invalid time"; continue
        if due > now:
            continue
        try:
            send_email(row["target"], row["recipient"], row["subject"], row["body"], row.get("in_reply_to", ""), row.get("references", ""))
            update_sales_status(row["target"])
            row["status"] = "sent"; row["sent_at"] = now.isoformat(); sent += 1
        except RuntimeError:
            row["status"] = "send failed"
    with CALENDAR.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows)
    return {"checked": len(rows), "sent": sent}


def events() -> list[dict]:
    """Return internal calendar events for the local visual calendar."""
    if not CALENDAR.exists():
        return []
    with CALENDAR.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
