"""Remove tracker rows that are clearly web articles/directories rather than companies."""
import csv
from pathlib import Path

from sourcing_agent import looks_like_article_or_list

TRACKER = Path(__file__).resolve().parent.parent / "x-security-master-tracker.csv"


def clean() -> tuple[int, int]:
    with TRACKER.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0].keys())
    valid = [row for row in rows if not looks_like_article_or_list(row.get("Target", ""), row.get("Company Website", ""))]
    with TRACKER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(valid)
    return len(rows) - len(valid), len(valid)


if __name__ == "__main__":
    removed, kept = clean()
    print(f"Removed {removed} invalid article/list row(s); kept {kept} real account row(s).")
