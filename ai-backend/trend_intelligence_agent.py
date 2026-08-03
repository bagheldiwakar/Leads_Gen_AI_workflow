"""Fetch, verify, store, and share one current trend for short X-Security outreach."""
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from product_context import read_product_context

TRENDS_PATH = Path(__file__).resolve().parent / "data" / "trends.md"


def relevant_trend(account: dict[str, str]) -> str:
    """Return one active trend note when one is available; never invent a trend."""
    if not TRENDS_PATH.exists():
        return ""
    text = TRENDS_PATH.read_text(encoding="utf-8").strip()
    if "No active trends have been added yet." in text:
        return ""
    # A later refresh job writes a concise active trend at the top of this file.
    for line in text.splitlines():
        if line.startswith("- Insight:"):
            return line.removeprefix("- Insight:").strip()
    return ""


def refresh_trend(account: dict[str, str]) -> dict[str, str]:
    """Find one public security trend and write it to shared trend memory."""
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        raise RuntimeError("TAVILY_API_KEY is not configured.")
    target = account.get("Target", "")
    role = account.get("Primary Role", "CTO")
    target_type = account.get("Target Type", "managed security provider")
    hypothesis = account.get("buying_hypothesis", "endpoint security")
    payload = {
        "api_key": tavily_key,
        "query": f"recent {target_type} trends relevant to selling B2B endpoint security antivirus to a {role}: {hypothesis}",
        "max_results": 3,
        "search_depth": "advanced",
    }
    request = Request("https://api.tavily.com/search", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=60) as response:
        results = json.loads(response.read().decode()).get("results", [])
    if not results:
        raise RuntimeError("No public trend source was found.")
    source = results[0].get("url", "")
    evidence = "\n".join(item.get("content", "")[:1500] for item in results)
    insight = evidence[:360].replace("\n", " ").strip()
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            from langchain_groq import ChatGroq
            prompt = f"""Using only this public evidence, write one factual, useful trend for a short CTO email about X-Security.
Product context: {read_product_context()}
Maximum 28 words. No hype, no prediction, no invented numbers. Return only the insight text.\nEvidence:\n{evidence[:4000]}"""
            insight = ChatGroq(api_key=groq_key, model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), temperature=0.1).invoke(prompt).content.strip()
        except Exception:
            pass
    insight = re.sub(r"\s+", " ", insight)[:420]
    today = date.today()
    TRENDS_PATH.write_text(
        "# X-Security Trend Intelligence Memory\n\n"
        "## Current endpoint-security trend\n"
        f"- Date found: {today.isoformat()}\n"
        f"- Account: {target}\n"
        f"- Segment: {target_type}\n"
        f"- Insight: {insight}\n"
        f"- Source: {source}\n"
        f"- Expires: {(today + timedelta(days=7)).isoformat()}\n",
        encoding="utf-8",
    )
    return {"insight": insight, "source": source, "expires": (today + timedelta(days=7)).isoformat()}
