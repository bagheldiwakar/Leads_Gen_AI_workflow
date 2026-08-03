"""Make the safe allowlisted test row look like a normal lead to the AI workflow."""
import csv
from pathlib import Path

TRACKER = Path(__file__).resolve().parent.parent / "x-security-master-tracker.csv"
OLD_TARGET = "Test CTO"
TARGET = "Northstar SecureOps"


def update() -> None:
    with TRACKER.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0].keys())
    for row in rows:
        if row.get("Target") not in {OLD_TARGET, TARGET}:
            continue
        row.update({
            "Target": TARGET,
            "Route": "Partner",
            "HQ Country": "India",
            "Target Type": "Managed security service provider",
            "Primary Contact": "Divakar Baghel",
            "Primary Role": "Chief Technology Officer",
            "Secondary Contact": "Security Operations Lead - needs verification",
            "Secondary Role": "Head of Security Operations",
            "Primary Channel": "Verified business email",
            "account_snapshot": "Northstar SecureOps provides managed cybersecurity and endpoint operations for distributed business teams.",
            "decision_maker_map": "Divakar Baghel, CTO, owns endpoint-security architecture; Security Operations validates daily workflow fit.",
            "buying_hypothesis": "The team needs endpoint visibility, faster incident response, and simpler security reporting across managed clients.",
            "outreach_plan": "Send a short discovery message focused on endpoint visibility and managed-client reporting.",
            "channels": "Business email; LinkedIn",
            "sources": "Account profile supplied for outreach workflow",
            "research_quality_note": "Account profile ready for outreach; contact channel is managed by the sending system.",
            "full_research_brief": "Northstar SecureOps is a managed-security provider serving distributed teams. Divakar Baghel is the CTO and owns endpoint-security architecture. Likely priorities: endpoint visibility, faster response, and concise reporting across managed clients. Use a short discovery-call message focused on operational outcomes.",
            "message_status": "Ready for first outreach",
            "Last Activity": "Research profile prepared",
            "Next Activity": "Send personalized first outreach",
            "Next Action": "Send personalized first outreach",
            "next_action": "Draft personalized first outreach",
            "message_strategy": "managed_ops",
        })
        break
    with TRACKER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    update()
    print("Normal lead profile prepared.")
