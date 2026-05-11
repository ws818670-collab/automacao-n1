import sys
sys.path.insert(0, '.')
from jira.client import JiraClient

try:
    client = JiraClient()
    
    issue = client.get_issue('JDMSN1-2709')
    if issue:
        fields = issue.get('fields', {})
        print(f"Chave: {issue.get('key')}")
        print(f"Resumo: {fields.get('summary')}")
        desc = fields.get('description')
        if desc and isinstance(desc, str):
            print(f"Descrição: {desc[:500]}")
        else:
            print("Descrição: [sem descrição ou formato inválido]")
        produto = fields.get('customfield_10200')
        if isinstance(produto, dict):
            print(f"Produto: {produto.get('value', '[vazio]')}")
        else:
            print(f"Produto: {produto or '[não preenchido]'}")
        status = fields.get('status', {})
        print(f"Status: {status.get('name', '[desconhecido]') if isinstance(status, dict) else status}")
    else:
        print('Chamado não encontrado')
except Exception as e:
    print(f'Erro: {str(e)[:200]}')
