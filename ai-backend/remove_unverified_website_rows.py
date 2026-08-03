"""Remove sourced rows whose saved website does not match the account brand."""
import csv
from pathlib import Path

from sourcing_agent import domain_matches_company

TRACKER = Path(__file__).resolve().parent.parent / "x-security-master-tracker.csv"


def clean() -> tuple[int, int]:
    with TRACKER.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0].keys())
    valid = []
    for row in rows:
        website = row.get("Company Website", "")
        if row.get("Target") == "Test CTO" or not website.startswith("http") or domain_matches_company(row.get("Target", ""), website):
            valid.append(row)
    with TRACKER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(valid)
    return len(rows) - len(valid), len(valid)


if __name__ == "__main__":
    removed, kept = clean()
    print(f"Removed {removed} row(s) with an unverified company website; kept {kept} row(s).")
