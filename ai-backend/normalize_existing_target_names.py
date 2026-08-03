"""Normalize page-title targets already saved before the sourcing-name fix."""
import csv
from pathlib import Path

from sourcing_agent import company_name_from_title

TRACKER = Path(__file__).resolve().parent.parent / "x-security-master-tracker.csv"


def normalize() -> int:
    with TRACKER.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0].keys())
    changed = 0
    for row in rows:
        old = row.get("Target", "")
        if "|" in old:
            row["Target"] = company_name_from_title(old)
            changed += 1
    with TRACKER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return changed


if __name__ == "__main__":
    print(f"Normalized {normalize()} target name(s).")
