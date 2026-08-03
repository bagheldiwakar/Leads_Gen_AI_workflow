"""Read new Gmail replies and land them in CSV for X-Security agents."""
import csv
import email
import imaplib
import os
from datetime import datetime
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path

from messaging import log, update_lead

BASE_DIR = Path(__file__).resolve().parent
REPLIES_PATH = BASE_DIR / "data" / "gmail_replies.csv"
LOG_PATH = BASE_DIR / "data" / "message_log.csv"
THREADS_PATH = BASE_DIR / "data" / "gmail_outbound_threads.csv"
REPLY_FIELDS = ["gmail_uid", "target", "sender_email", "subject", "received_at", "reply_body", "summary", "next_action"]

def _decode(value: str | None) -> str:
    if not value: return ""
    parts=[]
    for content, charset in decode_header(value):
        parts.append(content.decode(charset or "utf-8", errors="replace") if isinstance(content, bytes) else content)
    return "".join(parts)

def _body(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace").strip()
        return ""
    return message.get_payload(decode=True).decode(message.get_content_charset() or "utf-8", errors="replace").strip()

def _latest_reply_text(body: str) -> str:
    """Keep only the sender's new words; discard quoted thread history."""
    lines = []
    for line in body.splitlines():
        if line.strip().startswith(">") or line.lstrip().lower().startswith("on ") and " wrote:" in line.lower():
            break
        lines.append(line)
    return "\n".join(lines).strip()

def _existing_uids() -> set[str]:
    if not REPLIES_PATH.exists(): return set()
    with REPLIES_PATH.open(encoding="utf-8-sig", newline="") as handle:
        return {row.get("gmail_uid", "") for row in csv.DictReader(handle)}

def _target_for_sender(sender: str) -> str:
    """Match the sender to the most recently contacted account, without thread-ID verification."""
    if not THREADS_PATH.exists(): return ""
    with THREADS_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in reversed(list(csv.DictReader(handle))):
            if row.get("recipient", "").strip().lower() != sender.lower(): continue
            return row.get("target", "")
    return ""

def _tracked_recipients() -> set[str]:
    """Return only addresses that the Message Agent has actually emailed."""
    if not THREADS_PATH.exists():
        return set()
    with THREADS_PATH.open(encoding="utf-8-sig", newline="") as handle:
        return {row.get("recipient", "").strip().lower() for row in csv.DictReader(handle) if row.get("recipient", "").strip()}

def _classify(text: str) -> tuple[str, str, str]:
    value=text.lower()
    negative = (
        "not interested", "unsubscribe", "remove me", "do not contact", "stop emailing",
        "don't want", "dont want", "do not want", "don't like", "dont like", "no thanks",
        "not for us", "not a priority", "no need",
    )
    if any(word in value for word in negative):
        return "Negative reply or opt-out.", "Pause outreach and respect the request.", "Paused"
    if any(word in value for word in ("meeting", "call", "interested", "demo")):
        return "Positive buying signal in Gmail reply.", "Offer two times for a discovery call.", "Replied"
    return "Gmail reply received; needs review.", "Review the reply and prepare a relevant response.", "Replied"

def _explicit_opt_out(text: str) -> bool:
    value = text.lower()
    return any(word in value for word in ("unsubscribe", "remove me", "do not contact", "stop emailing"))

def sync_gmail_replies(limit: int = 20) -> dict:
    smtp_email=os.getenv("SMTP_EMAIL", "")
    app_password=os.getenv("SMTP_APP_PASSWORD", "")
    if not smtp_email or not app_password:
        raise RuntimeError("Gmail credentials are not configured.")
    processed=[]; existing=_existing_uids()
    try:
        mailbox=imaplib.IMAP4_SSL("imap.gmail.com")
        mailbox.login(smtp_email, app_password)
        # We mark a reply as seen only after it has been safely recorded.  This
        # prevents an already-synced reply from continuing to look "new" in
        # Gmail and confusing the operator.
        mailbox.select("INBOX", readonly=False)
        # Only search unread messages from recipients that the Message Agent actually contacted.
        # This avoids reading unrelated inbox mail while allowing more than one tracked account.
        tracked_recipients = _tracked_recipients()
        if not tracked_recipients:
            mailbox.logout()
            return {"checked": True, "new_replies": []}
        unread_uids: set[bytes] = set()
        for recipient in tracked_recipients:
            status, data = mailbox.uid("search", None, "UNSEEN", "FROM", f'"{recipient}"')
            if status != "OK": raise RuntimeError("Gmail could not search the tracked reply inbox.")
            unread_uids.update(data[0].split())
        for uid_bytes in sorted(unread_uids)[-max(1, min(limit, 50)):]:
            uid=uid_bytes.decode()
            if uid in existing:
                # This reply was already written to the tracker during an
                # earlier run.  Clear its unread flag without reading any
                # unrelated email.
                mailbox.uid("store", uid_bytes, "+FLAGS", "(\\Seen)")
                continue
            status, payload=mailbox.uid("fetch", uid_bytes, "(RFC822)")
            if status != "OK" or not payload or not payload[0]: continue
            message=email.message_from_bytes(payload[0][1])
            sender=parseaddr(message.get("From", ""))[1]
            subject=_decode(message.get("Subject"))
            body=_latest_reply_text(_body(message))
            if not body: continue
            target=_target_for_sender(sender)
            # Ignore only senders the Message Agent has never contacted.
            if not target: continue
            summary,next_action,stage=_classify(body)
            new_file=not REPLIES_PATH.exists(); REPLIES_PATH.parent.mkdir(exist_ok=True)
            with REPLIES_PATH.open("a", encoding="utf-8", newline="") as handle:
                writer=csv.DictWriter(handle, fieldnames=REPLY_FIELDS)
                if new_file: writer.writeheader()
                writer.writerow({"gmail_uid":uid,"target":target,"sender_email":sender,"subject":subject,"received_at":datetime.now().isoformat(),"reply_body":body,"summary":summary,"next_action":next_action})
            log(target,"email",sender,subject,body,"reply_received",summary,next_action)
            update_lead(target,message_status="Gmail reply received",latest_reply=body,reply_summary=summary,Stage=stage,last_update=datetime.now().strftime("%Y-%m-%d"),next_action=next_action)
            # Keep thread metadata in memory for the reply sender. It is not saved in the lead CSV.
            processed.append({
                "target": target,
                "sender_email": sender,
                "summary": summary,
                "explicit_opt_out": _explicit_opt_out(body),
                "subject": subject,
                "message_id": message.get("Message-ID", ""),
                "references": (message.get("References", "") + " " + message.get("In-Reply-To", "")).strip(),
            })
            # Only mark it read after the CSV and tracker updates succeeded.
            mailbox.uid("store", uid_bytes, "+FLAGS", "(\\Seen)")
        mailbox.logout()
        return {"checked": True, "new_replies": processed}
    except imaplib.IMAP4.error as error:
        raise RuntimeError("Gmail IMAP login failed. Check the Gmail address and app password.") from error
