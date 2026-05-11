import sys
sys.path.insert(0, '.')
from jira.client import JiraClient, normalize_issue

try:
    client = JiraClient()
    
    issue = client.get_issue('JDMSN1-2709')
    if issue:
        normalized = normalize_issue(issue)
        print(f"Chave: {normalized['chave_jira']}")
        print(f"\nResumo: {normalized['resumo']}")
        print(f"\nDescrição: {normalized['descricao']}")
        print(f"\nProduto: {normalized.get('produto', '[não preenchido]')}")
        print(f"\nComentários: {normalized['comentarios']}")
    else:
        print('Chamado não encontrado')
except Exception as e:
    print(f'Erro: {str(e)[:300]}')
