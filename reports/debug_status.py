import sys
sys.path.insert(0, '.')
from jira.client import JiraClient

client = JiraClient()
# Busca tickets com status "Concluído"
jql = 'project = JDMSN1 AND created >= "2026-01-01" AND created <= "2026-04-30" AND status = "Concluído" ORDER BY created ASC'
issues = client.search_issues(jql, max_results=5)
print(f"Tickets com status Concluído: {len(issues)}")
for i in issues:
    f = i["fields"]
    print(i["key"], "|", (f.get("status") or {}).get("name"), "|",
          "resdt:", f.get("resolutiondate"), "|",
          "updated:", f.get("updated", "")[:16])
