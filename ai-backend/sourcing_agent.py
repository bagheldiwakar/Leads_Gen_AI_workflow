"""X-Security sourcing agent: web-search, qualify and save up to 10 new leads per run."""
import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
TRACKER_PATH = BASE_DIR.parent / "x-security-master-tracker.csv"
MAX_LEADS_PER_RUN = 10
MIN_FIT_SCORE = 70
NON_COMPANY_TITLE_WORDS = ("top ", "directory", "list of", "guide", "report", "article", "best ")

TRACKER_FIELDS = [
    "Target", "Route", "HQ Country", "Target Type", "Priority", "Primary Contact",
    "Primary Role", "Secondary Contact", "Secondary Role", "Primary Channel",
    "Message Angle", "Stage", "Last Activity", "Next Activity", "Next Action",
    "Outcome", "Company Website", "Evidence Link", "account_snapshot", "decision_maker_map",
    "buying_hypothesis", "outreach_plan", "channels", "sources",
    "research_quality_note", "full_research_brief", "message_status", "next_action",
    "last_update", "latest_reply", "reply_summary", "message_strategy",
]


def tavily_search(query: str, max_results: int) -> list[dict]:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY is missing from ai-backend/.env")
    payload = {"api_key": key, "query": query, "max_results": max(1, min(max_results, 10)), "search_depth": "advanced"}
    request = Request("https://api.tavily.com/search", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode()).get("results", [])


def extract_company_names(results: list[dict], limit: int) -> list[str]:
    """Extract real company brands from web evidence, never using a result-page title as the account."""
    fallback = [company_name_from_title(item.get("title", "")) for item in results]
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return fallback[:limit]
    evidence = "\n".join(f"TITLE: {item.get('title', '')}\nCONTENT: {item.get('content', '')[:900]}" for item in results)
    try:
        from langchain_groq import ChatGroq
        prompt = f"""Find up to {limit} real B2B cybersecurity or managed-service COMPANY NAMES in this public web evidence.
Return only JSON like {{\"companies\":[\"Company A\",\"Company B\"]}}.
Never return an article title, directory, publisher, list, or generic category. Do not invent a company name.
Evidence:\n{evidence[:6000]}"""
        text = ChatGroq(api_key=api_key, model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), temperature=0).invoke(prompt).content
        match = re.search(r"\{.*\}", text, re.DOTALL)
        names = json.loads(match.group(0) if match else text).get("companies", [])
        return [str(name).strip() for name in names if str(name).strip()][:limit]
    except Exception:
        return fallback[:limit]


def official_company_page(company: str) -> dict | None:
    """Find a public company page for a named company; reject listicles and generic explainer pages."""
    results = tavily_search(f'"{company}" official website managed security cybersecurity', 3)
    for item in results:
        title, url = item.get("title", ""), item.get("url", "")
        if url.startswith("http") and not looks_like_article_or_list(title, url) and domain_matches_company(company, url):
            return item
    return None


def homepage_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/" if parts.scheme and parts.netloc else url


def call_groq_web_search(limit: int = MAX_LEADS_PER_RUN) -> list[dict]:
    discovery = tavily_search("global MSSP managed security services cybersecurity companies", max(limit * 2, 6))
    leads = []
    for company in extract_company_names(discovery, limit * 2):
        official = official_company_page(company)
        if not official:
            continue
        leads.append({
            "company_name": company,
            "website": homepage_url(official.get("url", "")),
            "company_type": "Needs AI qualification",
            "fit_score": 70,
            "fit_reason": official.get("content", "")[:500],
            "target_roles": "CTO; CISO",
            "outreach_angle": "Research endpoint-security and managed-service fit",
            "source_url": official.get("url", ""),
        })
        if len(leads) >= limit:
            break
    return leads


def normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())

def canonical_domain(value: str) -> str:
    return urlsplit(value).netloc.lower().removeprefix("www.")


def looks_like_article_or_list(title: str, url: str) -> bool:
    """Never treat a ranking, directory, or blog post as a customer account."""
    value = f"{title} {url}".lower()
    return any(word in value for word in NON_COMPANY_TITLE_WORDS) or "/resources/" in value or "/top" in value


def company_name_from_title(title: str) -> str:
    """Keep the brand portion of a search title, not the whole page headline."""
    parts = [part.strip() for part in title.split("|") if part.strip()]
    candidate = parts[-1] if len(parts) > 1 else title.strip()
    return re.sub(r"\s*\([^)]*\)\s*$", "", candidate).strip()


def domain_matches_company(company: str, url: str) -> bool:
    """The official-site domain must resemble the company brand."""
    company_key = normalized_name(company)
    domain_key = normalized_name(canonical_domain(url).split(".")[0])
    return bool(company_key and domain_key and (company_key.startswith(domain_key) or domain_key.startswith(company_key)))

def load_existing_keys() -> tuple[set[str], set[str]]:
    if not TRACKER_PATH.exists():
        return set(), set()
    with TRACKER_PATH.open(encoding="utf-8-sig", newline="") as file:
        rows=list(csv.DictReader(file))
    return ({canonical_domain(row.get("Evidence Link", "")) for row in rows}, {normalized_name(row.get("Target", "")) for row in rows})


def validate(lead: dict) -> dict | None:
    required = ["company_name", "website", "company_type", "fit_score", "fit_reason", "source_url"]
    if any(not str(lead.get(key, "")).strip() for key in required):
        return None
    try:
        score = int(float(lead["fit_score"]))
    except (TypeError, ValueError):
        return None
    if score < MIN_FIT_SCORE:
        return None
    website = str(lead["website"]).strip()
    source = str(lead["source_url"]).strip()
    if not (website.startswith("http") and source.startswith("http")):
        return None
    return {
        "date_sourced": str(date.today()),
        "company_name": str(lead["company_name"]).strip(),
        "website": website,
        "headquarters": str(lead.get("headquarters", "")).strip(),
        "company_type": str(lead["company_type"]).strip(),
        "fit_score": score,
        "fit_reason": str(lead["fit_reason"]).strip(),
        "target_roles": str(lead.get("target_roles", "CTO; CISO")).strip(),
        "outreach_angle": str(lead.get("outreach_angle", "")).strip(),
        "source_url": source,
        "status": "New — needs review",
    }


def to_tracker_row(lead: dict) -> dict:
    return {
        "Target": lead["company_name"], "Route": "Partner", "HQ Country": lead["headquarters"],
        "Target Type": lead["company_type"], "Priority": "Tier 1" if lead["fit_score"] >= 85 else "Tier 2",
        "Primary Contact": "Needs verification", "Primary Role": "CTO", "Secondary Contact": "Needs verification",
        "Secondary Role": "CISO or Security leader", "Primary Channel": "LinkedIn, then verified business email",
        "Message Angle": lead["outreach_angle"], "Stage": "Sourced - needs deep research",
        "Last Activity": "Not contacted", "Next Activity": "Run Deep Research Agent", "Next Action": "Run Deep Research Agent",
        "Outcome": "No response", "Company Website": lead["website"], "Evidence Link": lead["source_url"],
        "account_snapshot": f"Sourced {lead['date_sourced']} from {lead['source_url']}",
        "decision_maker_map": "CTO; CISO - needs verification", "buying_hypothesis": lead["fit_reason"],
        "outreach_plan": "Wait for deep research before outreach.", "channels": "LinkedIn; verified business email",
        "sources": lead["source_url"], "research_quality_note": "Initial web sourcing; deep research pending.",
        "full_research_brief": "Deep research pending.", "message_status": "Not started", "next_action": "Run Deep Research Agent",
        "last_update": "Not updated yet", "latest_reply": "No reply yet", "reply_summary": "No reply yet", "message_strategy": "Pending Learning Agent",
    }


def save(leads: list[dict]) -> list[dict]:
    existing_domains, existing_names = load_existing_keys()
    new_rows = []
    for lead in leads:
        row = validate(lead)
        domain=canonical_domain(row["website"]) if row else ""
        name=normalized_name(row["company_name"]) if row else ""
        if row and not looks_like_article_or_list(row["company_name"], row["website"]) and domain and name and domain not in existing_domains and name not in existing_names:
            new_rows.append(row)
            existing_domains.add(domain); existing_names.add(name)

    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not TRACKER_PATH.exists()
    with TRACKER_PATH.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=TRACKER_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(to_tracker_row(row) for row in new_rows)
    return new_rows

def run(limit: int = MAX_LEADS_PER_RUN) -> list[dict]:
    return save(call_groq_web_search(limit))


if __name__ == "__main__":
    try:
        saved = run()
        print(f"Saved {len(saved)} unique new leads to {TRACKER_PATH.name}.")
    except Exception as error:
        print(f"Sourcing failed: {error}", file=sys.stderr)
        raise
