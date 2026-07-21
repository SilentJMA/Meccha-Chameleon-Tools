#!/usr/bin/env python3
"""GitHub Issue Standards Check."""
import json, re, sys

R1 = re.compile(r"summary|describe the bug|one.?line", re.I)
R2 = re.compile(r"steps?[ \t]+(to[ \t]+)?reproduce|to[ \t]+reproduce|reproduction", re.I)
R3 = re.compile(r"expected[ \t]+(behavior|behaviour|result)", re.I)
R4 = re.compile(r"actual[ \t]+(behavior|behaviour|result)", re.I)
R5 = re.compile(r"(os|operating[ \t]+system|game[ \t]+version|tool[ \t]+version)", re.I)
R6 = re.compile(r"problem|what[ \t]+problem|motivation", re.I)
R7 = re.compile(r"solution|proposed|how[ \t]+should", re.I)
R8 = re.compile(r"question|what[ \t]+do[ \t]+you[ \t]+need", re.I)
R9 = re.compile(r"context|tried|checked", re.I)
R10 = re.compile(r"summary|feature[ \t]+description", re.I)

BUG_CHECKS = [("summary", R1), ("steps", R2), ("expected", R3), ("actual", R4), ("environment", R5)]
FEAT_CHECKS = [("summary", R10), ("problem", R6), ("solution", R7)]
SUPP_CHECKS = [("question", R8), ("context", R9), ("environment", R5)]

def check(body, checks):
    return [name for name, pat in checks if not pat.search(body)]

def main():
    raw = sys.stdin.read()
    try: data = json.loads(raw)
    except: print(json.dumps({"error": "Invalid JSON"})); sys.exit(1)
    body = data.get("body", "")
    title = data.get("title", "")
    labels = [l.get("name", "") for l in data.get("labels", [])]
    itype = data.get("issue_type", "bug")
    if "feature" in labels or "feature" in title.lower(): itype = "feature"
    elif "question" in labels or "?" in title: itype = "support"
    c = {"feature": FEAT_CHECKS, "support": SUPP_CHECKS}.get(itype, BUG_CHECKS)
    missing = check(body, c)
    v = {"issue_type": itype, "issue_number": data.get("number", 0), "complete": len(missing) == 0, "missing_fields": missing}
    print(json.dumps(v, indent=2))
    sys.exit(0 if v["complete"] else 1)

if __name__ == "__main__": main()
