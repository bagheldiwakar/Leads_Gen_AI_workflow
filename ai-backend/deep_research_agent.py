"""Deep-research agent: enrich newly sourced leads in the same CSV."""
import csv
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
CSV_PATH = BASE_DIR.parent / "x-security-master-tracker.csv"
MAX_LEADS_PER_RUN = 10


def web_research(company: str, website: str) -> dict:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY is missing from ai-backend/.env")
    prompt = f"""Research this B2B company using web search: {company}, website: {website}.
Return ONLY one JSON object with these fields:
company_summary, primary_decision_role, secondary_decision_role, public_profile_url,
active_platform, likely_security_need, personalized_outreach_angle, research_source_url.

Rules: use only public evidence; a public professional profile URL must be current and
verified by the search result; leave public_profile_url empty if no verified result exists;
do not guess email addresses; use a company or official source URL as research_source_url."""
    payload = {"api_key": key, "query": f"{company} cybersecurity CTO managed security", "max_results": 3, "search_depth": "advanced"}
    request = Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        results = json.loads(response.read().decode()).get("results", [])
    source = results[0].get("url", website) if results else website
    evidence = "\n\n".join(
        f"SOURCE: {item.get('url', '')}\nTITLE: {item.get('title', '')}\nCONTENT: {item.get('content', '')[:1800]}"
        for item in results
    )
    return analyze_evidence(company, website, source, evidence)


def analyze_evidence(company: str, website: str, source: str, evidence: str) -> dict:
    """Turn Tavily evidence into useful structured research; never invent private contact data."""
    fallback = {
        "company_summary": evidence[:1200] or "Public company summary was not found.",
        "primary_decision_role": "CTO - needs verification",
        "secondary_decision_role": "CISO or Security leader - needs verification",
        "public_profile_url": "Not publicly found",
        "active_platform": "LinkedIn - needs verification",
        "likely_security_need": "Validate during discovery",
        "personalized_outreach_angle": "Endpoint security and managed-service operations",
        "research_source_url": source or website,
    }
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not evidence:
        return fallback
    try:
        from langchain_groq import ChatGroq
        prompt = f"""You research public B2B accounts for X-Security endpoint security.
Use ONLY the supplied public evidence. Do not invent a person, email, phone number, company website, or performance claim.
Return ONLY a JSON object with exactly these string fields:
company_summary, primary_decision_role, secondary_decision_role, public_profile_url,
active_platform, likely_security_need, personalized_outreach_angle, research_source_url.
If a fact is unavailable, write 'Needs verification' (for profile use 'Not publicly found').
Target name: {company}
Known website: {website}
Public evidence:\n{evidence[:5000]}"""
        response = ChatGroq(
            api_key=api_key,
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            temperature=0.1,
        ).invoke(prompt).content.strip()
        match = re.search(r"\{.*\}", response, re.DOTALL)
        parsed = json.loads(match.group(0) if match else response)
        return {key: str(parsed.get(key) or fallback[key]).strip() for key in fallback}
    except Exception:
        return fallback


def classify_target_type(text: str) -> str:
    """Use public company language to classify without inventing a buyer type."""
    value = text.lower()
    if "managed security service" in value or "mssp" in value:
        return "MSSP"
    if "managed service provider" in value or "managed it service" in value or " msp" in value:
        return "MSP"
    if "systems integrator" in value or "system integrator" in value or "consulting" in value:
        return "Systems Integrator"
    if "endpoint" in value or "cybersecurity" in value or "security team" in value:
        return "Direct customer / security buyer"
    return "Needs human review"


def run(only_websites: set[str] | None = None, limit: int = MAX_LEADS_PER_RUN, force: bool = False) -> int:
    if not CSV_PATH.exists():
        raise RuntimeError("The master tracker does not exist. Run sourcing first.")
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
        fields = list(rows[0].keys()) if rows else []
    updated = 0
    for row in rows:
        company_website = row.get("Company Website", "")
        website = company_website if company_website.startswith("http") else row.get("Evidence Link", "")
        domain=urlsplit(website).netloc.lower().removeprefix("www.")
        if not website.startswith("http") or updated >= max(1, min(limit, MAX_LEADS_PER_RUN)) or (not force and row.get("Stage") != "Sourced - needs deep research") or (only_websites is not None and domain not in only_websites):
            continue
        try:
            research = web_research(row["Target"], website)
            research_text = " ".join(str(value) for value in research.values())
            row["Target Type"] = classify_target_type(research_text)
            row["account_snapshot"] = research.get("company_summary", "")
            row["Primary Role"] = research.get("primary_decision_role", "CTO")
            row["Secondary Role"] = research.get("secondary_decision_role", "CISO")
            row["Primary Channel"] = research.get("active_platform", "LinkedIn")
            row["Message Angle"] = research.get("personalized_outreach_angle", "Endpoint-security operations")
            row["buying_hypothesis"] = research.get("likely_security_need", "Validate during discovery")
            row["Company Website"] = website
            row["Evidence Link"] = research.get("research_source_url", website)
            row["sources"] = research.get("research_source_url", website)
            row["decision_maker_map"] = f"Primary: {row['Primary Role']}; Secondary: {row['Secondary Role']}"
            row["full_research_brief"] = "\n".join(f"{key}: {value}" for key, value in research.items() if value)
            row["research_quality_note"] = "Public web research complete; verify contact details before outreach."
            row["Primary Contact"] = row.get("Primary Contact") or "Needs verification"
            row["Secondary Contact"] = row.get("Secondary Contact") or "Needs verification"
            row["Last Activity"] = "Deep research completed"
            row["last_update"] = "Deep research completed"
            row["latest_reply"] = row.get("latest_reply") or "No reply yet"
            row["reply_summary"] = row.get("reply_summary") or "No reply yet"
            row["message_strategy"] = row.get("message_strategy") or "Pending Learning Agent"
            row["Stage"] = "Research ready"
            row["Next Activity"] = "Review research and draft outreach"
            row["Next Action"] = "Review research and draft outreach"
            updated += 1
        except Exception as error:
            row["research_quality_note"] = f"Needs retry: {type(error).__name__}"

    with CSV_PATH.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return updated


if __name__ == "__main__":
    try:
        print(f"Deep research completed for {run()} new leads.")
    except Exception as error:
        print(f"Deep research failed: {error}", file=sys.stderr)
        raise
