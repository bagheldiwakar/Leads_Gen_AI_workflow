"""Run the X-Security sourcing → deep-research CSV pipeline once or every hour."""
import argparse
import csv
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from deep_research_agent import run as research_run
from sourcing_agent import run as sourcing_run

BASE_DIR = Path(__file__).resolve().parent
RUN_LOG = BASE_DIR / "data" / "pipeline_runs.csv"

def run_sourcing(limit: int = 3) -> dict:
    sourced=sourcing_run(limit)
    return {"new_leads":len(sourced),"websites":[row["website"] for row in sourced]}

def run_deep_research(websites: list[str], limit: int = 3) -> dict:
    researched=research_run({urlsplit(site).netloc.lower().removeprefix("www.") for site in websites}, limit) if websites else 0
    return {"researched_leads":researched}

def run_once(limit: int = 3) -> dict:
    source_result=run_sourcing(limit)
    research_result=run_deep_research(source_result["websites"], limit)
    exists=RUN_LOG.exists(); RUN_LOG.parent.mkdir(exist_ok=True)
    with RUN_LOG.open("a",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=["run_at","new_leads","researched_leads","status"])
        if not exists: writer.writeheader()
        writer.writerow({"run_at":datetime.now().isoformat(),"new_leads":source_result["new_leads"],"researched_leads":research_result["researched_leads"],"status":"complete"})
    return {"new_leads":source_result["new_leads"],"researched_leads":research_result["researched_leads"],"status":"complete"}

if __name__ == "__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--hourly",action="store_true"); args=parser.parse_args()
    while True:
        print(run_once())
        if not args.hourly: break
        time.sleep(3600)
