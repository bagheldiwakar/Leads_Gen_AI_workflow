import os
import csv
import asyncio
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from messaging import configured as messaging_configured, log as message_log, send_email, send_whatsapp, update_lead
from learning_agent import choose_strategy, learning_summary
from ideas_agent import all_ideas, create_idea
from human_insight_agent import ask as ask_human_insight
from gmail_reply_agent import sync_gmail_replies
from pipeline_scheduler import run_once as run_pipeline_once, run_sourcing, run_deep_research
from trend_intelligence_agent import relevant_trend, refresh_trend
from product_context import read_product_context, save_product_context
from learning_monitor import state as monitor_state, set_enabled as set_monitor_enabled, record_check
from lead_status_agent import update_account as update_lead_status
from internal_calendar_agent import schedule_email, run_due_events, events as calendar_events

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
MEMORY_PATH = BASE_DIR / "data" / "internal.md"


def load_target_row(target: str) -> dict[str, str]:
    """Load a single account row from the shared master tracker."""
    tracker = BASE_DIR.parent / "x-security-master-tracker.csv"
    if not tracker.exists():
        return {}
    with tracker.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("Target", "").strip().lower() == target.strip().lower():
                return row
    return {}


def load_target_brief(target: str) -> str:
    """Load research from the single master CSV, not separate text files."""
    row = load_target_row(target)
    if row:
        return row.get("full_research_brief") or "\n".join(f"{key}: {value}" for key,value in row.items() if value)
    return "No target research was found; use the supplied target fields only."


def draft_with_groq(account: dict[str, str], strategy: str, trend: str, mode: str = "first_outreach") -> str:
    """Create one brief, evidence-based email; fall back safely when Groq is unavailable."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return ""
    try:
        from langchain_groq import ChatGroq
        if mode == "close_reply":
            follow_up_rule = "This is a warm closing reply after the prospect said they do not want the offer. Thank them briefly, respect their decision, say there is no further action needed, and do not pitch, ask for a meeting, or try to reopen the sale."
        elif mode == "scheduled_meeting":
            follow_up_rule = "This is a short, friendly email to send at the meeting time the prospect requested. Confirm you are available, make no sales pitch, and ask whether the time still works."
        elif mode == "reply_followup":
            follow_up_rule = "This is a reply follow-up. Acknowledge the reply and be consultative and helpful, never pushy or salesy. Offer a useful next step or a concise answer."
        else:
            follow_up_rule = "This is a first outreach. Be informative first, not hype."
        prompt = f"""Write a short B2B email (maximum 85 words) for X-Security.
{follow_up_rule} Include one useful trend only if supplied. End with a low-pressure request for a 15-minute discovery call only when appropriate. Do not invent claims, contact details, attachments, links, meetings, or product capabilities that were not supplied. Never say that something is attached unless an attachment was actually provided. Return email body only.
Company: {account.get('Target', '')}
Contact: {account.get('Primary Contact', '')}
Role: {account.get('Primary Role', '')}
Research: {account.get('full_research_brief', '')[:2400]}
Product context: {read_product_context()}
Message strategy: {strategy}
Trend: {trend or 'No current trend supplied'}"""
        return ChatGroq(
            api_key=api_key,
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            temperature=0.3,
        ).invoke(prompt).content.strip()
    except Exception:
        return ""

app = FastAPI(title="X-Security AI Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this before deploying.
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/visual", StaticFiles(directory=str(BASE_DIR.parent), html=True), name="visual")

@app.get("/api/master-tracker")
def master_tracker() -> list[dict[str, str]]:
    """Expose shared lead memory to the Command Center; never includes credentials."""
    tracker = BASE_DIR.parent / "x-security-master-tracker.csv"
    if not tracker.exists():
        return []
    with tracker.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@app.get("/api/internal-calendar")
def internal_calendar() -> list[dict]:
    return calendar_events()

async def learning_monitor_loop() -> None:
    """Read only the allowlisted Gmail reply thread at a respectful five-minute interval."""
    last_run = 0.0
    while True:
        settings = monitor_state()
        now = __import__("time").time()
        if settings["enabled"] and now - last_run >= settings["interval_seconds"]:
            try:
                result = sync_gmail_replies(limit=10)
                reply_count = len(result.get("new_replies", []))
                # Re-evaluate shared strategy after new outcome data lands in the tracker.
                choose_strategy("Northstar SecureOps")
                record_check(reply_count=reply_count)
            except Exception as error:
                record_check(error=type(error).__name__)
            last_run = now
        try:
            run_due_events()
        except Exception:
            pass
        await asyncio.sleep(15)

@app.on_event("startup")
async def start_learning_monitor() -> None:
    asyncio.create_task(learning_monitor_loop())

@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, error: Exception):
    """Last-resort handler: return a safe error and do not expose credentials or stack traces."""
    return JSONResponse(status_code=500, content={"ok": False, "detail": "The messaging service could not complete that request safely."})


class RecommendationRequest(BaseModel):
    target: str
    target_type: str = ""
    decision_maker: str = ""
    stage: str = "Research ready"
    outcome: str = "No response"
    message_angle: str = "Endpoint visibility and centralized policy"
    notes: str = ""


class RecommendationResponse(BaseModel):
    score: int
    lifecycle_stage: Literal["Lead", "MQL", "SQL"]
    summary: str
    next_action: str
    message_draft: str
    source: Literal["baseline", "groq"]


class SourcedLead(BaseModel):
    target: str
    target_type: str
    reason: str
    priority: str

class MessageDraftRequest(BaseModel):
    target: str
    channel: Literal["email", "whatsapp"]
    recipient: str = ""
    notes: str = ""
    mode: Literal["first_outreach", "reply_followup", "close_reply", "scheduled_meeting"] = "first_outreach"
    use_trend: bool = True

class SendTestRequest(BaseModel):
    target: str
    channel: Literal["email", "whatsapp"]
    recipient: str
    body: str
    subject: str = "X-Security: quick question"

class ReplyStatusRequest(BaseModel):
    target: str
    channel: Literal["email", "whatsapp"]
    sender: str
    reply_text: str

class CampaignIdeaRequest(BaseModel):
    idea: str
    scope: Literal["All accounts", "Segment", "Account"] = "All accounts"
    scope_value: str = ""
    status: Literal["Draft", "Active", "Paused", "Archived"] = "Draft"
    priority: int = 50
    end_date: str = ""
    test_group: str = ""

class HumanInsightRequest(BaseModel):
    question: str

class DeepResearchRunRequest(BaseModel):
    websites: list[str]
    limit: int = 3

class TrendRefreshRequest(BaseModel):
    target: str = "Northstar SecureOps"

class ProductPromptRequest(BaseModel):
    content: str

class LearningMonitorRequest(BaseModel):
    enabled: bool


def source_candidates(limit: int = 10) -> list[SourcedLead]:
    """Return current live accounts from the one shared master tracker."""
    tracker = BASE_DIR.parent / "x-security-master-tracker.csv"
    if not tracker.exists():
        return []
    with tracker.open(encoding="utf-8-sig", newline="") as handle:
        pool = list(csv.DictReader(handle))
    return [
        SourcedLead(
            target=row.get("Target", ""),
            target_type=row.get("Target Type", ""),
            priority=row.get("Priority", "Tier 3"),
            reason=row.get("buying_hypothesis", "Fits the X-Security partner profile."),
        )
        for row in pool[:limit]
    ]


def score_lead(stage: str, outcome: str) -> tuple[int, str]:
    score = 20
    if stage in {"Contacted", "Replied"}:
        score += 10
    if stage in {"Discovery booked", "Qualified"}:
        score += 35
    if stage in {"Pilot proposed", "Pilot active"}:
        score += 55
    if stage == "Closed won":
        score += 70
    if outcome in {"Positive reply", "Discovery call booked"}:
        score += 20
    if outcome in {"Qualified opportunity", "Pilot proposed", "Pilot active", "Closed won"}:
        score += 35

    score = min(score, 100)
    return score, "SQL" if score >= 60 else "MQL" if score >= 40 else "Lead"


def baseline_recommendation(request: RecommendationRequest) -> RecommendationResponse:
    score, lifecycle = score_lead(request.stage, request.outcome)
    if lifecycle == "SQL":
        next_action = "Hand off to sales and confirm the problem, executive sponsor, pilot scope, and next meeting."
    elif lifecycle == "MQL":
        next_action = "Continue discovery and ask one question about the current endpoint-security process."
    else:
        next_action = "Send the first personalized outreach message or the next planned follow-up."

    draft = (
        f"Hi [First Name] — I’m researching how {request.target} approaches endpoint-security operations. "
        "We are building X-Security for teams that need better endpoint visibility, response workflows, "
        "and reporting. Open to a brief 15-minute exchange on what is hardest today?"
    )
    return RecommendationResponse(
        score=score,
        lifecycle_stage=lifecycle,
        summary="Baseline recommendation: no Groq API key is configured or no real outcome history is available.",
        next_action=next_action,
        message_draft=draft,
        source="baseline",
    )


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "memory_file": str(MEMORY_PATH),
    }


@app.get("/api/tracker/summary")
def tracker_summary() -> dict:
    """Live counts from the master tracker, the shared memory for every agent."""
    tracker = BASE_DIR.parent / "x-security-master-tracker.csv"
    if not tracker.exists():
        return {"total_leads": 0, "research_ready": 0, "pending_research": 0}
    with tracker.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        "total_leads": len(rows),
        "research_ready": sum(row.get("Stage") == "Research ready" for row in rows),
        "pending_research": sum(row.get("Stage") == "Sourced - needs deep research" for row in rows),
    }


@app.get("/api/messaging/status")
def messaging_status() -> dict:
    """Safe configuration check; it deliberately never returns credentials."""
    return messaging_configured()

@app.get("/api/learning-monitor")
def get_learning_monitor() -> dict:
    return monitor_state()

@app.post("/api/learning-monitor")
def update_learning_monitor(request: LearningMonitorRequest) -> dict:
    return set_monitor_enabled(request.enabled)

@app.post("/api/trends/refresh")
def refresh_trend_memory(request: TrendRefreshRequest) -> dict:
    """Refresh one public trend before a short first-outreach draft."""
    try:
        account = load_target_row(request.target)
        if not account:
            raise RuntimeError("The selected account was not found in the Master Tracker.")
        return refresh_trend(account)
    except (RuntimeError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Trend Intelligence could not refresh a public trend.") from error

@app.get("/api/product-prompt")
def get_product_prompt() -> dict:
    return {"content": read_product_context()}

@app.post("/api/product-prompt")
def update_product_prompt(request: ProductPromptRequest) -> dict:
    try:
        return {"content": save_product_context(request.content), "saved": True}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

@app.post("/api/gmail/sync-replies")
def gmail_sync_replies(limit: int = 20) -> dict:
    """Fetch new inbox replies once; never exposes credentials or message data in errors."""
    try:
        return sync_gmail_replies(limit)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

@app.post("/api/gmail/sync-and-learn")
def gmail_sync_and_learn(limit: int = 20) -> dict:
    """Sync a tracked reply, learn a strategy, and safely send its follow-up to the test allowlist only."""
    try:
        result = sync_gmail_replies(limit)
        follow_ups = []
        recipient = os.getenv("TEST_EMAIL_RECIPIENT", "").strip()
        if result.get("new_replies") and not recipient:
            raise RuntimeError("The Gmail test recipient is not configured.")
        for reply in result.get("new_replies", []):
            target = reply["target"]
            account = load_target_row(target)
            if account.get("Stage") == "Paused" and reply.get("explicit_opt_out"):
                continue
            learning = choose_strategy(target)
            reply_subject = reply.get("subject", "X-Security: a question about endpoint operations")
            if not reply_subject.lower().startswith("re:"):
                reply_subject = f"Re: {reply_subject}"
            mode = "close_reply" if account.get("Stage") == "Paused" else "reply_followup"
            draft = message_draft(MessageDraftRequest(
                target=target,
                channel="email",
                recipient=recipient,
                mode=mode,
                use_trend=False,
            ))
            delivery = send_email(
                target,
                recipient,
                reply_subject,
                draft["body"],
                in_reply_to=reply.get("message_id", ""),
                references=reply.get("references", ""),
            )
            # The Sales Agent runs only after the Message Agent has written its send result to the tracker.
            sales_status = update_lead_status(load_target_row(target))
            meeting_time = sales_status.get("Meeting Time", "")
            if meeting_time:
                scheduled = message_draft(MessageDraftRequest(
                    target=target, channel="email", recipient=recipient,
                    mode="scheduled_meeting", use_trend=False,
                ))
                schedule_email(
                    target, meeting_time, recipient, reply_subject, scheduled["body"],
                    in_reply_to=reply.get("message_id", ""), references=reply.get("references", ""),
                )
            if mode == "close_reply":
                update_lead(
                    target,
                    message_strategy=learning["strategy"],
                    message_status="Warm acknowledgement sent",
                    Stage="Paused",
                    next_action="No further outreach unless the prospect re-engages.",
                )
            else:
                update_lead(
                    target,
                    message_strategy=learning["strategy"],
                    message_status="Helpful follow-up sent",
                    next_action="Wait for a reply to the helpful follow-up.",
                )
            follow_ups.append({"target": target, "strategy": learning["strategy"], "status": delivery["status"], "mode": mode, "scheduled_for": meeting_time})
        public_replies = [
            {"target": reply["target"], "sender_email": reply["sender_email"], "summary": reply["summary"]}
            for reply in result.get("new_replies", [])
        ]
        return {"checked": result.get("checked", False), "new_replies": public_replies, "learning_ran": bool(public_replies), "follow_ups": follow_ups}
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

@app.post("/api/pipeline/run-once")
def pipeline_run_once(limit: int = 3) -> dict:
    """Run sourcing then deep research in order, with CSV-based de-duplication."""
    try:
        return run_pipeline_once(max(1, min(limit, 3)))
    except (RuntimeError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="The sourcing pipeline could not complete.") from error

@app.post("/api/pipeline/source")
def pipeline_source(limit: int = 3) -> dict:
    try:
        return run_sourcing(max(1, min(limit, 3)))
    except (RuntimeError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Sourcing could not complete.") from error

@app.post("/api/pipeline/deep-research")
def pipeline_deep_research(request: DeepResearchRunRequest) -> dict:
    try:
        return run_deep_research(request.websites, max(1, min(request.limit, 3)))
    except (RuntimeError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Deep research could not complete.") from error

@app.get("/api/ideas")
def campaign_ideas() -> list[dict]:
    return all_ideas()

@app.post("/api/ideas")
def add_campaign_idea(request: CampaignIdeaRequest) -> dict:
    try:
        return create_idea(request.model_dump())
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Could not save that campaign idea.") from error

@app.post("/api/human-insight")
def human_insight(request: HumanInsightRequest) -> dict:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Ask a campaign or strategy question.")
    return ask_human_insight(request.question)


@app.post("/api/message/draft")
def message_draft(request: MessageDraftRequest) -> dict:
    brief = load_target_brief(request.target)
    account = load_target_row(request.target)
    learning = choose_strategy(request.target)
    strategy = learning["strategy"]
    angle = learning["instruction"].lower()
    human_instruction = learning.get("human_instruction", "")
    human_line = f" Your campaign direction: {human_instruction}" if human_instruction else ""
    contact = account.get("Primary Contact", "").strip()
    role = account.get("Primary Role", "").strip()
    trend = relevant_trend(account) if request.use_trend else ""
    first_name = contact.split()[0] if contact and "verification" not in contact.lower() else "[First Name]"
    role_context = f" As {role} at {request.target}," if role and "verification" not in role.lower() else ""
    subject = "X-Security: a question about endpoint operations" if request.channel == "email" else ""
    if request.mode == "close_reply":
        body = "Hi [First Name],\n\nThank you for letting me know. I appreciate your reply and will not take any further action.\n\nBest,\n[Your Name]"
    elif request.mode == "scheduled_meeting":
        body = "Hi [First Name],\n\nJust checking in as requested. I am available to connect now—does the time still work for you?\n\nBest,\n[Your Name]"
    elif request.channel == "email":
        body = ("Hi [First Name],\n\n"
                f"I’m looking at how {request.target} manages endpoint security. X-Security focuses on {angle}{human_line} "
                "Would you be open to a 15-minute discovery call next week?\n\nBest,\n[Your Name]")
    else:
        body = (f"Hi [First Name] — I’m researching endpoint-security operations at {request.target}. "
                f"X-Security focuses on {angle}{human_line} Would you be open to a short 15-minute conversation?")
    body = body.replace("Hi [First Name]", f"Hi {first_name}", 1)
    if role_context and request.mode not in {"close_reply", "scheduled_meeting"}:
        if request.channel == "email":
            body = body.replace("\n\n", f"\n\n{role_context.strip()} ", 1)
        else:
            body = f"{body} {role_context.strip()}"
    if trend:
        body = body.replace("Would you be open", f"One current market signal: {trend} Would you be open", 1)
    groq_body = draft_with_groq(account, strategy, trend, request.mode)
    if groq_body:
        body = groq_body
    next_action = "Respect the decision; do not send further outreach unless they re-engage." if request.mode == "close_reply" else ("Internal calendar will send this at the scheduled meeting time." if request.mode == "scheduled_meeting" else f"strategy={strategy}; review draft before a test send.")
    message_log(request.target, request.channel, request.recipient, subject, body, "drafted", next_action=next_action)
    update_lead(request.target, message_status="Draft ready", message_strategy=strategy, next_action=next_action)
    return {"target": request.target, "channel": request.channel, "subject": subject, "body": body, "source": "groq" if groq_body else "learning_agent", "strategy": strategy, "strategy_basis": learning["basis"], "human_ideas": learning.get("human_ideas", []), "research_found": not brief.startswith("No target research"), "mode": request.mode, "trend_used": bool(trend)}

    # Legacy baseline kept below only for reference; execution returns above.
    if request.channel == "email":
        subject = f"X-Security: a question about endpoint operations"
        body = (
            "Hi [First Name],\n\n"
            f"I’m looking at how {request.target} manages endpoint security and reporting. "
            "X-Security is designed to improve endpoint visibility and response workflows. "
            "Would you be open to a 15-minute discovery call next week?\n\nBest,\n[Your Name]"
        )
    else:
        subject = ""
        body = (
            f"Hi [First Name] — I’m researching endpoint-security operations at {request.target}. "
            "Would you be open to a short 15-minute conversation about visibility and response workflows?"
        )
    # A draft is logged, but nothing is sent by this endpoint.
    message_log(request.target, request.channel, request.recipient, subject, body, "drafted", next_action="Review draft before a test send.")
    update_lead(request.target, message_status="Draft ready", next_action="Review draft before a test send.")
    return {"target": request.target, "channel": request.channel, "subject": subject, "body": body, "source": "baseline", "research_found": not brief.startswith("No target research")}


@app.post("/api/message/send-test")
def message_send_test(request: SendTestRequest) -> dict:
    try:
        result = send_email(request.target, request.recipient, request.subject, request.body) if request.channel == "email" else send_whatsapp(request.target, request.recipient, request.body)
        update_lead_status(load_target_row(request.target))
        return {"ok": True, "channel": request.channel, **result}
    except RuntimeError as error:
        # Convert all delivery failures into a clear API error while retaining the CSV audit entry.
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/demo/start-messaging")
def start_demo_messaging() -> dict:
    """Demo-only safe send: Test CTO can send only to the configured Gmail test recipient."""
    recipient = os.getenv("TEST_EMAIL_RECIPIENT", "").strip()
    if not recipient:
        raise HTTPException(status_code=400, detail="The Gmail test recipient is not configured.")
    try:
        target = "Northstar SecureOps"
        draft = message_draft(MessageDraftRequest(target=target, channel="email", recipient=recipient))
        result = send_email(target, recipient, draft["subject"], draft["body"])
        update_lead_status(load_target_row(target))
        return {"ok": True, "target": target, "status": result["status"], "next_action": "Reply to this thread from the configured inbox, then run Gmail reply sync."}
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/message/reply-status")
def message_reply_status(request: ReplyStatusRequest) -> dict:
    text = request.reply_text.lower()
    if any(word in text for word in ("don't want", "dont want", "do not want", "don't like", "dont like", "no thanks", "not interested", "unsubscribe", "remove me", "do not contact", "stop emailing", "not for us", "not a priority", "no need")):
        summary, next_action, stage = "Negative reply or opt-out.", "Pause outreach and respect the request.", "Paused"
    elif any(word in text for word in ("meeting", "call", "interested", "demo")):
        summary, next_action, stage = "Positive buying signal in reply.", "Offer two times for a discovery call.", "Replied"
    else:
        summary, next_action, stage = "Reply received; needs human review.", "Review the reply and prepare a relevant response.", "Replied"
    message_log(request.target, request.channel, request.sender, "", request.reply_text, "reply_received", summary, next_action)
    update_lead(request.target, message_status="Reply received", latest_reply=request.reply_text, reply_summary=summary, Stage=stage, last_update=__import__("datetime").datetime.now().strftime("%Y-%m-%d"), next_action=next_action)
    return {"ok": True, "summary": summary, "next_action": next_action, "stage": stage, "learning": choose_strategy(request.target)}


@app.get("/api/message/log")
def message_history(limit: int = 50) -> list[dict]:
    path = BASE_DIR / "data" / "message_log.csv"
    if not path.exists(): return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))[-max(1, min(limit, 200)):]


@app.get("/api/learning/status")
def learning_status() -> dict:
    return {"patterns": learning_summary(), "rule": "It learns only from aggregate logged outcomes; the Message Agent core prompt remains stable."}

@app.get("/api/learning/account/{target}")
def account_learning_status(target: str) -> dict:
    log_path=BASE_DIR / "data" / "message_log.csv"
    history=[]
    if log_path.exists():
        with log_path.open(encoding="utf-8-sig", newline="") as handle:
            history=[row for row in csv.DictReader(handle) if row.get("target", "").strip().lower()==target.strip().lower()][-10:]
    return {"target":target, "learning":choose_strategy(target), "recent_messages":history}


@app.post("/api/recommendation", response_model=RecommendationResponse)
def recommendation(request: RecommendationRequest) -> RecommendationResponse:
    baseline = baseline_recommendation(request)
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return baseline

    try:
        from langchain_groq import ChatGroq

        memory = MEMORY_PATH.read_text(encoding="utf-8")
        target_brief = load_target_brief(request.target)
        prompt = f"""You are an AI assistant for an X-Security B2B outreach dashboard.
Use the internal learning memory below. Do not invent performance data.
Return exactly four lines:
Summary: ...
Next action: ...
Message draft: ...
Reason: ...

Internal memory:
{memory}

Target brief:
{target_brief}

Target: {request.target}
Target type: {request.target_type}
Decision maker: {request.decision_maker}
Stage: {request.stage}
Outcome: {request.outcome}
Message angle: {request.message_angle}
Notes: {request.notes}
"""
        llm = ChatGroq(
            api_key=api_key,
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            temperature=0.2,
        )
        response = llm.invoke(prompt).content
        lines = {
            line.split(":", 1)[0].strip().lower(): line.split(":", 1)[1].strip()
            for line in response.splitlines()
            if ":" in line
        }
        return RecommendationResponse(
            score=baseline.score,
            lifecycle_stage=baseline.lifecycle_stage,
            summary=lines.get("summary", baseline.summary),
            next_action=lines.get("next action", baseline.next_action),
            message_draft=lines.get("message draft", baseline.message_draft),
            source="groq",
        )
    except Exception as error:
        return baseline.model_copy(
            update={"summary": f"Groq was unavailable; using the baseline recommendation. ({type(error).__name__})"}
        )


@app.get("/api/source-leads", response_model=list[SourcedLead])
def source_leads(limit: int = 10) -> list[SourcedLead]:
    """Return AI-ready, high-fit leads from the researched global account pool."""
    return source_candidates(max(1, min(limit, 20)))
