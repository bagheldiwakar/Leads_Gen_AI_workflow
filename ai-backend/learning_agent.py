"""Shared learning layer: selects an outreach strategy without sending messages."""
import csv
from collections import defaultdict
from pathlib import Path
from ideas_agent import active_for

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "data" / "message_log.csv"
PATTERNS = {
    "visibility": "Endpoint visibility and centralized policy.",
    "response": "Faster endpoint investigation and response.",
    "managed_ops": "Multi-client managed-security operations.",
    "reporting": "Clear security reporting and proof of value.",
    "pilot": "A limited, low-risk endpoint-security pilot.",
}

def account_segment(target: str) -> str:
    tracker = BASE_DIR.parent / "x-security-master-tracker.csv"
    if not tracker.exists(): return "general"
    with tracker.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("Target", "").strip().lower() == target.strip().lower():
                text = " ".join(row.values()).lower()
                if any(word in text for word in ("mssp", "msp", "managed service", "reseller", "integrator")): return "partner"
                if any(word in text for word in ("finance", "bank", "insurance")): return "finance"
                return "technology"
    return "general"

def learning_summary() -> dict:
    stats = defaultdict(lambda: {"drafts": 0, "positive_replies": 0, "negative_replies": 0})
    if not LOG_PATH.exists(): return dict(stats)
    latest = {}
    with LOG_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            target=row.get("target", "").lower(); text=(row.get("next_action", "")+row.get("body", "")).lower()
            if row.get("status") == "drafted":
                strategy=next((name for name in PATTERNS if f"strategy={name}" in text), "visibility")
                latest[target]=strategy; stats[strategy]["drafts"] += 1
            elif row.get("status") == "reply_received":
                strategy=latest.get(target, "visibility"); reply=row.get("body", "").lower()
                if any(word in reply for word in ("meeting", "call", "interested", "demo")): stats[strategy]["positive_replies"] += 1
                if any(word in reply for word in ("not interested", "unsubscribe", "remove me")): stats[strategy]["negative_replies"] += 1
    return dict(stats)

def choose_strategy(target: str) -> dict:
    segment=account_segment(target); baseline="managed_ops" if segment == "partner" else "reporting" if segment == "finance" else "visibility"
    human_ideas=active_for(target, segment)
    human_instruction=" ".join(item["idea"] for item in human_ideas)
    # A targeted human instruction deliberately takes precedence over generic learning.
    account_rules=[item for item in human_ideas if item.get("scope") == "Account" and item.get("scope_value", "").strip().lower() == target.strip().lower()]
    if account_rules:
        instruction=account_rules[0]["idea"]
        return {"strategy":"human_override", "instruction":instruction, "basis":"Active human instruction for this specific account.", "human_ideas":human_ideas, "human_instruction":instruction}
    eligible=[(name,values) for name,values in learning_summary().items() if values["drafts"] >= 5 and values["positive_replies"] + values["negative_replies"] >= 2]
    if eligible:
        name, values=max(eligible, key=lambda item:(item[1]["positive_replies"]/max(item[1]["drafts"],1), item[1]["positive_replies"]))
        return {"strategy":name, "instruction":PATTERNS[name], "basis":f"Aggregate result: {values['drafts']} drafts and {values['positive_replies']} positive replies.", "human_ideas":human_ideas, "human_instruction":human_instruction}
    return {"strategy":baseline, "instruction":PATTERNS[baseline], "basis":f"Baseline for this {segment} account; more results are needed before learning changes it.", "human_ideas":human_ideas, "human_instruction":human_instruction}
