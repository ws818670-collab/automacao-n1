import sys
sys.path.insert(0, '.')
from jira.client import JiraClient

client = JiraClient()
issues = client.search_issues('project = JDMSN1 AND created >= "2026-01-01" ORDER BY created DESC', max_results=5)
for issue in issues[:3]:
    f = issue.get('fields', {})
    print(f"Chave: {issue['key']}")
    print(f"  customfield_10069: {f.get('customfield_10069')}")
    print(f"  resolutiondate:    {f.get('resolutiondate')}")
    # Mostrar todos os campos custom não nulos
    for k, v in f.items():
        if k.startswith('customfield') and v is not None and v != '' and v != []:
            print(f"  {k}: {v}")
    print()
