import csv, os, smtplib, ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json

BASE_DIR=Path(__file__).resolve().parent
LOG=BASE_DIR/"data"/"message_log.csv"
FIELDS=["timestamp","target","channel","recipient","subject","body","status","reply_summary","next_action"]
TRACKER=BASE_DIR.parent/"x-security-master-tracker.csv"
THREADS=BASE_DIR/"data"/"gmail_outbound_threads.csv"
THREAD_FIELDS=["message_id","target","recipient","subject","sent_at"]

def configured():
    return {"gmail":bool(os.getenv("SMTP_EMAIL") and os.getenv("SMTP_APP_PASSWORD") and os.getenv("TEST_EMAIL_RECIPIENT")),"whatsapp":bool(os.getenv("WHATSAPP_ACCESS_TOKEN") and os.getenv("WHATSAPP_PHONE_NUMBER_ID") and os.getenv("WHATSAPP_TEST_RECIPIENT")),"test_mode":os.getenv("TEST_MODE","true").lower()=="true"}

def log(target,channel,recipient,subject,body,status,reply_summary="",next_action=""):
    exists=LOG.exists(); LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS)
        if not exists:w.writeheader()
        w.writerow({"timestamp":datetime.now().isoformat(),"target":target,"channel":channel,"recipient":recipient,"subject":subject,"body":body,"status":status,"reply_summary":reply_summary,"next_action":next_action})

def record_outbound_thread(message_id,target,recipient,subject):
    exists=THREADS.exists(); THREADS.parent.mkdir(exist_ok=True)
    with THREADS.open("a",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=THREAD_FIELDS)
        if not exists: writer.writeheader()
        writer.writerow({"message_id":message_id,"target":target,"recipient":recipient,"subject":subject,"sent_at":datetime.now().isoformat()})

def allowed(channel,recipient):
    if os.getenv("TEST_MODE","true").lower()!="true": return True
    key="TEST_EMAIL_RECIPIENT" if channel=="email" else "WHATSAPP_TEST_RECIPIENT"
    return recipient.strip()==os.getenv(key,"").strip()

def update_lead(target, **updates):
    """Persist messaging state on the matching master-tracker row."""
    if not TRACKER.exists():
        return
    with TRACKER.open(encoding="utf-8-sig", newline="") as f:
        rows=list(csv.DictReader(f)); fields=list(rows[0].keys()) if rows else []
    for key in updates:
        if key not in fields: fields.append(key)
    for row in rows:
        if row.get("Target", "").strip().lower()==target.strip().lower():
            row.update({key:str(value) for key,value in updates.items()})
            break
    else:
        return
    with TRACKER.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)

def send_email(target,recipient,subject,body,in_reply_to="",references=""):
    try:
        if not configured()["gmail"]: raise RuntimeError("Gmail test credentials are not configured.")
        if not allowed("email",recipient): raise PermissionError("Recipient is not on the Gmail test allowlist.")
        msg=EmailMessage();message_id=make_msgid(domain="x-security.local");msg["Message-ID"]=message_id;msg["From"]=os.environ["SMTP_EMAIL"];msg["To"]=recipient;msg["Subject"]=subject
        if in_reply_to:
            msg["In-Reply-To"]=in_reply_to
        if references:
            msg["References"]=references
        msg.set_content(body)
        with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context()) as s:
            s.login(os.environ["SMTP_EMAIL"],os.environ["SMTP_APP_PASSWORD"]);s.send_message(msg)
        log(target,"email",recipient,subject,body,"sent",next_action="Wait for test reply or review delivery.")
        record_outbound_thread(message_id,target,recipient,subject)
        update_lead(target,message_status="Email test sent",last_update=datetime.now().strftime("%Y-%m-%d"),next_action="Wait for test reply or review delivery.")
        return {"status":"sent"}
    except (PermissionError, RuntimeError, smtplib.SMTPException, OSError) as error:
        log(target,"email",recipient,subject,body,"failed",reply_summary=type(error).__name__)
        update_lead(target,message_status="Email test failed",last_update=datetime.now().strftime("%Y-%m-%d"))
        raise RuntimeError(str(error)) from error

def send_whatsapp(target,recipient,body):
    try:
        if not configured()["whatsapp"]: raise RuntimeError("WhatsApp test credentials are not configured.")
        if not allowed("whatsapp",recipient): raise PermissionError("Recipient is not on the WhatsApp test allowlist.")
        url=f"https://graph.facebook.com/v21.0/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
        payload={"messaging_product":"whatsapp","to":recipient.replace("+",""),"type":"text","text":{"body":body}}
        req=Request(url,data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {os.environ['WHATSAPP_ACCESS_TOKEN']}","Content-Type":"application/json"},method="POST")
        with urlopen(req,timeout=30): pass
        log(target,"whatsapp",recipient,"",body,"sent",next_action="Wait for test reply or review delivery.")
        update_lead(target,message_status="WhatsApp test sent",last_update=datetime.now().strftime("%Y-%m-%d"),next_action="Wait for test reply or review delivery.")
        return {"status":"sent"}
    except (PermissionError, RuntimeError, HTTPError, URLError, OSError) as error:
        log(target,"whatsapp",recipient,"",body,"failed",reply_summary=type(error).__name__)
        update_lead(target,message_status="WhatsApp test failed",last_update=datetime.now().strftime("%Y-%m-%d"))
        raise RuntimeError(str(error)) from error
