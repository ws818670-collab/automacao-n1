import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jira.client import JiraClient

client = JiraClient()
issues = client.search_issues(
    'project = JDMSN1 AND created >= "2026-01-01" AND created <= "2026-04-30" ORDER BY created ASC',
    max_results=10
)
for issue in issues:
    f = issue["fields"]
    sla = f.get("customfield_10051") or {}
    comp = sla.get("completedCycles", [])
    ong  = sla.get("ongoingCycle") or {}
    resdt = f.get("resolutiondate")
    status = (f.get("status") or {}).get("name", "")
    ong_ms = (ong.get("elapsedTime") or {}).get("millis", 0) if ong else 0
    comp_ms = sum(c.get("elapsedTime", {}).get("millis", 0) for c in comp)
    print(f"{issue['key']} | status={status!r:20} | resdt={str(resdt)[:10]} | comp_cycles={len(comp)} | comp_ms={comp_ms} | ong_ms={ong_ms}")
