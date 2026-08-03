"""LLM-assisted sales status decisions stored in the shared Master Tracker."""
import hashlib
import json
import os
import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from messaging import update_lead

BASE_DIR = Path(__file__).resolve().parent
CACHE_PATH = BASE_DIR / "data" / "sales_status_cache.json"
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def _explicit_meeting_time(reply: str) -> str:
    """Resolve simple weekday promises deterministically instead of trusting an LLM date guess."""
    text = (reply or "").lower()
    match = re.search(r"\b(?:this|on|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text)
    if not match:
        return ""
    weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
    now = datetime.now().astimezone()
    requested = weekdays[match.group(1)]
    offset = (requested - now.weekday()) % 7
    # "next Saturday" is always the following week; "this Saturday" can mean today.
    if match.group(0).startswith("next "):
        offset = offset or 7
    scheduled = (now + timedelta(days=offset)).replace(hour=18, minute=0, second=0, microsecond=0)
    return scheduled.isoformat()


def _fallback(account: dict[str, str]) -> dict[str, str]:
    """Safe fallback only if the LLM is unavailable."""
    stage = account.get("Stage", "").strip().lower()
    message_status = account.get("message_status", "").strip().lower()
    reply_summary = account.get("reply_summary", "").strip().lower()
    if stage == "paused" or "opt-out" in reply_summary or "negative" in reply_summary:
        return {"Lead Temperature": "Closed", "Status Summary": "Prospect declined or requested no further outreach.", "Follow-up Timing": "No follow-up unless the prospect re-engages.", "Sales Agent Model": "Fallback rules (LLM unavailable)"}
    if "positive" in reply_summary or stage in {"discovery booked", "qualified", "pilot proposed", "pilot active"}:
        return {"Lead Temperature": "Hot", "Status Summary": "A reply or strong buying signal needs prompt attention.", "Follow-up Timing": "Today — respond within one business day.", "Sales Agent Model": "Fallback rules (LLM unavailable)"}
    if stage == "replied" or "sent" in message_status or stage == "contacted":
        return {"Lead Temperature": "Warm", "Status Summary": "Outreach is active; wait for a response before escalating.", "Follow-up Timing": f"Follow up after {date.today() + timedelta(days=4):%d %b %Y} if there is no reply.", "Sales Agent Model": "Fallback rules (LLM unavailable)"}
    return {"Lead Temperature": "Cold", "Status Summary": "Research is available, but the account has not engaged yet.", "Follow-up Timing": "Verify the decision maker and start first outreach.", "Sales Agent Model": "Fallback rules (LLM unavailable)"}


def _input(account: dict[str, str]) -> dict[str, str]:
    return {key: account.get(key, "") for key in ("Target", "Target Type", "Primary Role", "Stage", "message_status", "latest_reply", "reply_summary", "next_action", "full_research_brief")}


def _signature(account: dict[str, str]) -> str:
    return hashlib.sha256(("sales-agent-v3|" + json.dumps(_input(account), sort_keys=True)).encode()).hexdigest()


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _llm_decision(account: dict[str, str]) -> dict[str, str] | None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    prompt = f"""You are a B2B sales operations analyst for X-Security. Read only the recorded account data below. Current local time is {datetime.now().astimezone().isoformat()}.
Choose a clear, short sales-pipeline status that fits the evidence. Examples include New Prospect, Contact Verified, First Outreach Sent, Nurture, Engaged — Needs Discovery, Discovery Ready, Objection Handling, Pilot Candidate, Closed — Not a Fit, or Do Not Contact. You may choose a better sales status if needed. A prospect who declined must never be treated as positive. Never invent facts.
If the customer proposes a time, including phrases such as “this Friday”, “today at 6”, or “after 15 minutes”, resolve it from the current local time and return the exact ISO 8601 time in meeting_time_iso. If no time is proposed, use an empty string. If a date is stated but no time is stated, use 18:00 local time.
Return only valid JSON with keys: lead_temperature, status_summary, follow_up_timing, decision_reason, meeting_time_iso. lead_temperature is the sales-pipeline status and must be at most 6 words. Each other value must be short.
Account data: {json.dumps(_input(account), ensure_ascii=False)}"""
    try:
        from langchain_groq import ChatGroq
        raw = ChatGroq(api_key=api_key, model=MODEL, temperature=0).invoke(prompt).content.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)
        temperature = str(result.get("lead_temperature", "")).strip()
        if not temperature or len(temperature.split()) > 6:
            return None
        meeting_time = str(result.get("meeting_time_iso", "")).strip()
        try:
            if meeting_time:
                datetime.fromisoformat(meeting_time)
        except ValueError:
            meeting_time = ""
        return {
            "Lead Temperature": temperature,
            "Status Summary": str(result.get("status_summary", ""))[:240] or "LLM status decision recorded.",
            "Follow-up Timing": str(result.get("follow_up_timing", ""))[:160] or "Review current account activity.",
            "Sales Agent Decision": str(result.get("decision_reason", ""))[:240],
            "Sales Agent Model": MODEL,
            "Meeting Time": meeting_time,
        }
    except Exception:
        return None


def update_account(account: dict[str, str]) -> dict[str, str]:
    """Use the LLM once per changed account record; cached results prevent repeat API calls."""
    target = account.get("Target", "").strip()
    if not target:
        return {}
    signature = _signature(account)
    cache = _load_cache()
    cached = cache.get(target, {})
    if cached.get("signature") == signature:
        return cached["result"]
    result = _llm_decision(account) or _fallback(account)
    explicit_time = _explicit_meeting_time(account.get("latest_reply", ""))
    if explicit_time:
        result["Meeting Time"] = explicit_time
        result["Follow-up Timing"] = "Meeting scheduled"
        result["Status Summary"] = "Prospect proposed a meeting time."
    cache[target] = {"signature": signature, "result": result}
    _save_cache(cache)
    update_lead(target, **result)
    return result


def update_target(target: str) -> dict[str, str]:
    """Reload the row after another agent writes to it, then make one sales decision."""
    tracker = BASE_DIR.parent / "x-security-master-tracker.csv"
    if not tracker.exists():
        return {}
    with tracker.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("Target", "").strip().lower() == target.strip().lower():
                return update_account(row)
    return {}
