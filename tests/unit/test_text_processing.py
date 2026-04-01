from processing.text_processing import clean_text, consolidate_ticket_text, extract_problem_solution_context


def test_clean_text_removes_extra_spaces() -> None:
    assert clean_text("erro   no   processamento") == "erro no processamento"


def test_consolidate_ticket_text_joins_non_empty_blocks() -> None:
    text = consolidate_ticket_text("Resumo", "Descricao", "Comentario")
    assert "Resumo" in text
    assert "Descricao" in text
    assert "Comentario" in text


def test_extract_problem_solution_context_finds_markers() -> None:
    problem, solution, context = extract_problem_solution_context(
        "Erro ao integrar nota fiscal. Caso resolvido apos ajuste no parametro."
    )
    assert "Erro" in problem or "erro" in problem.lower()
    assert "ajuste" in solution.lower() or "resolvido" in solution.lower()
    assert context