"""Add newly required columns to the shared Master Tracker without losing rows."""
import csv
from pathlib import Path

TRACKER = Path(__file__).resolve().parent.parent / "x-security-master-tracker.csv"
NEW_COLUMN = "Company Website"


def upgrade() -> int:
    with TRACKER.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0].keys()) if rows else []
    if NEW_COLUMN not in fields:
        fields.insert(fields.index("Evidence Link"), NEW_COLUMN)
    for row in rows:
        row.setdefault(NEW_COLUMN, "Not applicable" if row.get("Target") == "Test CTO" else "Needs verification")
    with TRACKER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    print(f"Upgraded {upgrade()} Master Tracker row(s).")
