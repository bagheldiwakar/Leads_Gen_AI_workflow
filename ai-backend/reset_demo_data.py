"""Reset active X-Security demo data while preserving the Test CTO account and project code."""
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parent

def keep_header(path: Path) -> None:
    if not path.exists(): return
    with path.open(encoding="utf-8-sig", newline="") as handle:
        fields=next(csv.reader(handle), [])
    if fields:
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(fields)

def reset() -> dict:
    tracker=ROOT / "x-security-master-tracker.csv"
    with tracker.open(encoding="utf-8-sig", newline="") as handle:
        rows=list(csv.DictReader(handle)); fields=list(rows[0].keys())
    test_rows=[row for row in rows if row.get("Target", "").strip().lower()=="test cto"]
    if len(test_rows) != 1:
        raise RuntimeError("Test CTO must exist exactly once before reset.")
    with tracker.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader(); writer.writerow(test_rows[0])
    for name in ("message_log.csv", "gmail_replies.csv", "gmail_outbound_threads.csv", "pipeline_runs.csv"):
        keep_header(BASE_DIR / "data" / name)
    return {"master_tracker_rows": 1, "kept_target": "Test CTO", "web_leads": 0}

if __name__ == "__main__":
    print(reset())
