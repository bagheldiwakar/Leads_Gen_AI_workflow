"""Convert saved official-site pages into clean company-homepage links."""
import csv
from pathlib import Path

from sourcing_agent import homepage_url

TRACKER = Path(__file__).resolve().parent.parent / "x-security-master-tracker.csv"


def normalize() -> int:
    with TRACKER.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0].keys())
    changed = 0
    for row in rows:
        website = row.get("Company Website", "")
        if website.startswith("http"):
            cleaned = homepage_url(website)
            if cleaned != website:
                row["Company Website"] = cleaned
                changed += 1
    with TRACKER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return changed


if __name__ == "__main__":
    print(f"Normalized {normalize()} company website link(s).")
