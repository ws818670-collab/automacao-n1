import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import httpx
import openpyxl

# Permite executar o script via "python tools/export_jql_to_csv.py"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jira.client import JiraClient, _extract_product_field, _extract_text_from_adf
from utils.config import get_settings


def _read_keys_from_xlsx(xlsx_path: str) -> list[str]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    keys: list[str] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        value = row[0] if row else None
        if isinstance(value, str) and value.strip():
            keys.append(value.strip())
    wb.close()
    return keys


def _search_issues_by_keys_batched(
    client: JiraClient,
    keys: list[str],
    batch_size: int = 100,
    max_results: int = 0,
) -> list[dict[str, Any]]:
    all_issues: list[dict[str, Any]] = []
    for start in range(0, len(keys), batch_size):
        if max_results > 0 and len(all_issues) >= max_results:
            break
        batch = keys[start : start + batch_size]
        keys_str = ", ".join(batch)
        jql = f"key in ({keys_str})"
        issues = client.search_issues(jql=jql, max_results=0)
        all_issues.extend(issues)
    if max_results > 0:
        return all_issues[:max_results]
    return all_issues


def _read_existing_keys_from_csv(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()

    existing: set[str] = set()
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = str(row.get("Chave da item") or "").strip()
            if key:
                existing.add(key)
    return existing


def _extract_comments(fields: dict[str, Any]) -> str:
    comments_data = fields.get("comment", {}).get("comments", [])
    parts: list[str] = []
    for comment in comments_data:
        text = _extract_text_from_adf(comment.get("body"))
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _get_reporter(fields: dict[str, Any]) -> str:
    reporter = fields.get("reporter") or {}
    if isinstance(reporter, dict):
        return str(reporter.get("displayName") or reporter.get("emailAddress") or "").strip()
    return ""


def _get_resolution(_fields: dict[str, Any]) -> str:
    # Campo reservado para uso futuro na curadoria.
    return ""


def _heuristic_summary(title: str, description: str, comments: str) -> str:
    desc = " ".join(description.split())
    comm = " ".join(comments.split())
    first_desc = desc[:260]
    first_comm = comm[:180]

    pieces = [f"Titulo: {title.strip()}"]
    if first_desc:
        pieces.append(f"Descricao: {first_desc}")
    if first_comm:
        pieces.append(f"Comentarios: {first_comm}")
    return " | ".join(pieces)


def _gemini_summary(settings: Any, title: str, description: str, comments: str) -> str:
    model = (settings.gemini_model or "gemini-2.5-flash").strip()
    if model.startswith("models/"):
        model = model.split("models/", 1)[1]

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    prompt = (
        "Resuma em portugues (Brasil), de forma objetiva e profissional, o chamado Jira. "
        "Use no maximo 2 frases. Nao invente dados."
    )
    body = {
        "system_instruction": {"parts": [{"text": prompt}]},
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            f"Titulo: {title}\n\n"
                            f"Descricao: {description[:4000]}\n\n"
                            f"Comentarios: {comments[:2500]}"
                        )
                    }
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2},
    }

    response = httpx.post(
        endpoint,
        params={"key": settings.gemini_api_key.strip()},
        json=body,
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "\n".join(str(part.get("text", "")).strip() for part in parts if part.get("text")).strip()
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta chamados Jira para CSV com colunas para curadoria.")
    parser.add_argument("--jql", default="", help="JQL customizado. Se vazio, usa KNOWLEDGE_BASE_JQL do .env")
    parser.add_argument(
        "--keys-xlsx",
        default="",
        help="Arquivo .xlsx com chaves curadas na 1a coluna (ex.: Base de conhecimento.xlsx).",
    )
    parser.add_argument("--max-results", type=int, default=0, help="Limite de issues. 0 = sem limite")
    parser.add_argument(
        "--use-ai-summary",
        action="store_true",
        help="Ativa resumo com Gemini para a coluna final. Sem esta flag, usa resumo heuristico.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Caminho de saida do CSV. Se vazio, cria em project/exports.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Se o arquivo de saida ja existir, preserva linhas existentes e continua apenas o que falta.",
    )
    args = parser.parse_args()

    settings = get_settings()
    client = JiraClient()

    issues: list[dict[str, Any]]
    if args.keys_xlsx.strip():
        keys = _read_keys_from_xlsx(args.keys_xlsx.strip())
        if not keys:
            raise ValueError("Nenhuma chave encontrada em --keys-xlsx.")
        issues = _search_issues_by_keys_batched(client, keys, max_results=args.max_results)
    else:
        jql = args.jql.strip() or settings.knowledge_base_jql.strip()
        if not jql:
            raise ValueError("JQL vazio. Informe --jql ou configure KNOWLEDGE_BASE_JQL.")
        issues = client.search_issues(jql=jql, max_results=args.max_results)

    out_dir = Path(__file__).resolve().parents[1] / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = Path(args.out) if args.out else out_dir / f"jira_base_curadoria_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    headers = [
        "Chave da item",
        "Resumo",
        "Relator",
        "Status",
        "Resolução",
        "Criado",
        "Produto",
        "Resumo do chamado após: Título - Descrição e comentários",
    ]

    existing_keys: set[str] = set()
    if args.resume:
        existing_keys = _read_existing_keys_from_csv(out_file)
        if existing_keys:
            issues = [issue for issue in issues if str(issue.get("key", "")).strip() not in existing_keys]

    write_mode = "a" if args.resume and out_file.exists() else "w"
    should_write_header = write_mode == "w"

    with out_file.open(write_mode, newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if should_write_header:
            writer.writeheader()

        for issue in issues:
            fields = issue.get("fields", {})
            key = str(issue.get("key", "")).strip()
            title = str(fields.get("summary", "")).strip()
            description = _extract_text_from_adf(fields.get("description"))
            comments = _extract_comments(fields)

            resumo_ia = ""
            if args.use_ai_summary and settings.gemini_api_key.strip():
                try:
                    resumo_ia = _gemini_summary(settings, title, description, comments)
                except Exception:
                    resumo_ia = ""

            if not resumo_ia:
                resumo_ia = _heuristic_summary(title, description, comments)

            writer.writerow(
                {
                    "Chave da item": key,
                    "Resumo": title,
                    "Relator": _get_reporter(fields),
                    "Status": str((fields.get("status") or {}).get("name") or "").strip(),
                    "Resolução": _get_resolution(fields),
                    "Criado": str(fields.get("created") or "").strip(),
                    "Produto": _extract_product_field(fields),
                    "Resumo do chamado após: Título - Descrição e comentários": resumo_ia,
                }
            )

    print(f"CSV gerado: {out_file}")
    print(f"Total de linhas: {len(issues)}")


if __name__ == "__main__":
    main()
