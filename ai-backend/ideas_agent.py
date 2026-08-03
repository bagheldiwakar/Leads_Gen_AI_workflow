"""Human campaign ideas: stored as structured, versioned CSV records."""
import csv
from datetime import date
from pathlib import Path
from uuid import uuid4

BASE_DIR=Path(__file__).resolve().parent
PATH=BASE_DIR / "data" / "campaign_ideas.csv"
FIELDS=["id","idea","scope","scope_value","status","priority","start_date","end_date","test_group","drafts","positive_replies","negative_replies","created_at"]

def all_ideas():
    if not PATH.exists(): return []
    with PATH.open(encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))

def create_idea(payload: dict):
    PATH.parent.mkdir(exist_ok=True); exists=PATH.exists()
    record={key:"" for key in FIELDS}
    record.update({key:str(value) for key,value in payload.items() if key in record})
    record.update({"id":uuid4().hex[:12],"status":payload.get("status","Draft"),"priority":payload.get("priority","50"),"start_date":payload.get("start_date",str(date.today())),"drafts":"0","positive_replies":"0","negative_replies":"0","created_at":str(date.today())})
    with PATH.open("a",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        if not exists: writer.writeheader()
        writer.writerow(record)
    return record

def active_for(target: str, segment: str):
    today=str(date.today()); ideas=[]
    for row in all_ideas():
        if row.get("status") != "Active": continue
        if row.get("end_date") and row["end_date"] < today: continue
        scope=row.get("scope","All accounts"); value=row.get("scope_value","").strip().lower()
        if scope=="All accounts" or (scope=="Account" and value==target.lower()) or (scope=="Segment" and value==segment.lower()): ideas.append(row)
    return sorted(ideas,key=lambda x:int(x.get("priority") or 50),reverse=True)[:3]
