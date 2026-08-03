"""Answers human questions using only the recorded campaign-ideas history."""
import re
from ideas_agent import all_ideas

def ask(question: str) -> dict:
    words={word for word in re.findall(r"[a-z0-9]+",question.lower()) if len(word)>3}
    matches=[]
    for idea in all_ideas():
        text=(idea.get("idea","")+" "+idea.get("scope_value","")).lower()
        overlap=sum(word in text for word in words)
        if overlap: matches.append((overlap,idea))
    matches.sort(key=lambda item:item[0],reverse=True)
    top=[idea for _,idea in matches[:5]]
    if not top:
        return {"answer":"No matching recorded campaign idea was found. You can save this as a new draft idea and test it safely.","matches":[]}
    lines=[]
    for idea in top:
        lines.append(f"{idea['idea']} — {idea['status']}; {idea.get('drafts','0')} drafts, {idea.get('positive_replies','0')} positive replies, {idea.get('negative_replies','0')} negative replies.")
    return {"answer":"Recorded campaign history: " + " ".join(lines),"matches":top}
