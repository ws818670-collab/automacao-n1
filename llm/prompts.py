def build_jira_analysis_prompt(role_ctx: str, produto: str = "") -> str:
    produto_ctx = f"Produto do chamado: {produto}\n" if produto else ""
    return (
        f"{role_ctx}\n\n"
        f"{produto_ctx}"
        "Sua tarefa agora: analisar o chamado aberto e os tickets relacionados do historico "
        "para gerar uma nota de triagem interna objetiva, pratica e acionavel para o atendente N1.\n"
        "A saida final deve seguir exatamente a estrutura exigida pelo template de triagem.\n\n"
        "REGRAS OBRIGATORIAS:\n"
        "- Use APENAS as informacoes fornecidas. Nunca invente dados, tickets ou solucoes.\n"
        "- Se nao houver solucao clara no historico, declare explicitamente.\n"
        "- Linguagem tecnica, direta, sem texto comercial.\n"
        "- Nao repita o titulo do chamado literalmente no campo cenario.\n"
        "- Considere o produto do chamado ao avaliar os tickets similares: priorize tickets do mesmo produto.\n"
        "- passos_n1 devem ser acoes concretas, verificaveis e alinhadas ao papel do N1 descrito acima.\n"
        "- Para escalonamento, aplique o criterio de indicacao descrito no papel do N1.\n\n"
        "Retorne APENAS JSON valido com estas chaves:\n"
        "- cenario: descricao objetiva do problema em 1-2 frases\n"
        "- causa_provavel: hipotese mais provavel com base no historico (ou 'Nao identificada')\n"
        "- chamados_relacionados: lista (2 a 4 itens) no formato {id, motivo_relacao}\n"
        "- analise_chamados: sintese do padrao em 2 a 4 linhas\n"
        "- acao_recomendada_n1: lista de passos claros, numerados e acionaveis para N1\n"
        "- criterios_escalonamento_n2: lista de bullets com condicoes objetivas para escalar\n"
        "- passos_n1: lista de exatamente 3 acoes especificas e verificaveis\n"
        "- indicacao: Resolver no N1 | Escalar para N2\n"
        "- confianca: Alta | Media | Baixa"
    )


def build_chat_prompt(role_ctx: str, produto: str = "") -> str:
    produto_ctx = f"Produto em contexto: {produto}\n" if produto else ""
    return (
        f"{role_ctx}\n\n"
        f"{produto_ctx}"
        "Com base nos tickets do historico fornecidos, responda a pergunta do atendente N1.\n"
        "REGRAS: use apenas o contexto fornecido; seja objetivo e tecnico; "
        "priorize tickets do mesmo produto; "
        "se a base nao tiver resposta clara, diga explicitamente.\n"
        "Retorne APENAS JSON valido com as chaves:\n"
        "- sintese: resumo do que foi identificado (1-2 frases)\n"
        "- padrao_observado: comportamento recorrente nos tickets similares\n"
        "- solucao_recorrente: acao que resolveu os casos anteriores (ou 'Sem solucao documentada')"
    )