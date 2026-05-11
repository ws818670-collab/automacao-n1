import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jira.client import JiraClient

client = JiraClient()

# Conta tickets que estão ou estiveram em "Aguardando retorno - Avalara"
jql_status = (
    'project = JDMSN1 '
    'AND created >= "2026-01-01" AND created <= "2026-04-28" '
    'AND status = "Aguardando retorno - Avalara" '
    'AND reporter != "douglas.souza@jdmsconsulting.com.br"'
)
issues_status = client.search_issues(jql_status, max_results=0)
print(f"Tickets ATUALMENTE em 'Aguardando retorno - Avalara': {len(issues_status)}")

# Verifica o campo customfield_10069 em tickets desse status
jql_field = (
    'project = JDMSN1 '
    'AND created >= "2026-01-01" AND created <= "2026-04-28" '
    'AND "customfield_10069" is not EMPTY'
)
try:
    issues_field = client.search_issues(jql_field, max_results=0)
    print(f"Tickets com customfield_10069 preenchido: {len(issues_field)}")
except Exception as e:
    print(f"Erro ao buscar pelo campo: {e}")

# Mostra os primeiros tickets do status Avalara com seus campos
print("\nPrimeiros tickets em status Avalara:")
for i in issues_status[:5]:
    f = i["fields"]
    print(f"  {i['key']} | cf10069={f.get('customfield_10069')!r}")
