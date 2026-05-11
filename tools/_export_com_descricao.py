import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from jira.client import JiraClient, _extract_text_from_adf, _extract_product_field
import openpyxl

client = JiraClient()
jql = (
    'project = JDMSN1 AND status IN ('
    '"Aguardando retorno - Avalara", '
    '"Aguardando Retorno \u2013 Cliente", '
    '"Analise JDMS", '
    'Conclu\u00eddo) AND created >= "2025-01-01"'
)

print("Buscando issues...")
issues = client.search_issues(jql)
print(f"Total: {len(issues)}")

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Issues"
ws.append(["Chave", "Resumo", "Descricao", "Status", "Relator", "Criado", "Produto", "URL"])

base_url = client.base_url
for issue in issues:
    key = issue.get("key", "")
    fields = issue.get("fields", {})
    summary = fields.get("summary", "")
    description = _extract_text_from_adf(fields.get("description"))
    status = fields.get("status", {}).get("name", "") if fields.get("status") else ""
    reporter = fields.get("reporter", {}).get("displayName", "") if fields.get("reporter") else ""
    created_raw = fields.get("created", "")
    try:
        created = datetime.fromisoformat(created_raw[:19]).strftime("%d/%m/%Y %H:%M")
    except Exception:
        created = created_raw
    produto = _extract_product_field(fields)
    url = f"{base_url}/browse/{key}"
    ws.append([key, summary, description, status, reporter, created, produto, url])

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports", f"jira_filter_10089_com_descricao_{ts}.xlsx")
wb.save(out)
print(f"Arquivo: {out}")
print(f"Linhas: {ws.max_row - 1}")
