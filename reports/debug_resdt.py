import sys
sys.path.insert(0, '.')
from jira.client import JiraClient

client = JiraClient()
jql = 'project = JDMSN1 AND created >= "2026-01-01" AND created <= "2026-04-30" AND resolution is not EMPTY ORDER BY created ASC'
issues = client.search_issues(jql, max_results=5)
for i in issues:
    f = i["fields"]
    print(i["key"], "|", (f.get("status") or {}).get("name"), "|", f.get("resolutiondate"))
