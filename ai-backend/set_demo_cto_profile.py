"""Set a clearly fictional profile for the safe Test CTO messaging demonstration."""
import csv
from pathlib import Path

TRACKER = Path(__file__).resolve().parent.parent / "x-security-master-tracker.csv"


def update() -> None:
    with TRACKER.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0].keys())
    for row in rows:
        if row.get("Target") != "Test CTO":
            continue
        row.update({
            "HQ Country": "Demo environment",
            "Target Type": "Fictional managed security provider - safe demo",
            "Primary Contact": "Alex Morgan (fictional demo CTO)",
            "Primary Role": "Chief Technology Officer",
            "Secondary Contact": "Jordan Lee (fictional demo security leader)",
            "Secondary Role": "Head of Security Operations",
            "Primary Channel": "Gmail test account only",
            "account_snapshot": "Fictional managed-security provider used only to demonstrate the X-Security workflow.",
            "decision_maker_map": "Alex Morgan (fictional CTO) owns endpoint tooling; Jordan Lee (fictional security leader) validates operations.",
            "buying_hypothesis": "The fictional team needs endpoint visibility, faster incident response, and simpler security reporting.",
            "outreach_plan": "Send a personalized Gmail test message only to the allowlisted demo inbox.",
            "full_research_brief": "Demo account only. Fictional CTO profile: Alex Morgan leads a managed-security team supporting remote endpoints. Likely priorities: endpoint visibility, faster response, and concise reporting. Use a short discovery-call message. Never treat this as a real prospect.",
            "research_quality_note": "Fictional profile for safe interview demonstration; no real customer data.",
            "message_strategy": "managed_ops",
        })
        break
    with TRACKER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    update()
    print("Test CTO fictional demo profile updated.")
