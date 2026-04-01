"""
Importa um CSV curado com resumo por IA para a base de conhecimento.

Uso:
  python tools/import_ai_curated_csv.py
  python tools/import_ai_curated_csv.py --csv "C:/.../jira_base_curadoria_ai_1095.csv"

O script usa o campo de resumo por IA como texto principal para embeddings,
melhorando a recuperação semântica na triagem.
"""

import argparse
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path

from dateutil import parser as date_parser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from embeddings.service import EmbeddingService
from ingestion.service import IngestionService
from jira.client import JiraClient
from models.database import SessionLocal, init_db
from models.repositories import sync_ticket_scope

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_CSV = Path(__file__).resolve().parents[2] / "jira_base_curadoria_ai_1095.csv"
AI_SUMMARY_COL = "Resumo do chamado após: Título - Descrição e comentários"


def _parse_date(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return date_parser.parse(text)
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa CSV curado com resumo por IA para a base vetorial.")
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV),
        help=f"Caminho do CSV curado com IA (padrão: {DEFAULT_CSV})",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV não encontrado: {csv_path}")

    init_db()
    jira_client = JiraClient()
    embedding_service = EmbeddingService()
    ingestion_service = IngestionService(jira_client, embedding_service)

    db = SessionLocal()
    processed = 0
    allowed_keys: set[str] = set()

    try:
        with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = str(row.get("Chave da item") or "").strip()
                if not key:
                    continue

                allowed_keys.add(key)
                resumo = str(row.get("Resumo") or "").strip()
                status = str(row.get("Status") or "").strip()
                produto = str(row.get("Produto") or "").strip()
                criado = _parse_date(str(row.get("Criado") or ""))
                resumo_ai = str(row.get(AI_SUMMARY_COL) or "").strip()

                # O resumo por IA vira o texto principal de conhecimento.
                ticket_data = {
                    "chave_jira": key,
                    "resumo": resumo,
                    "descricao": resumo_ai,
                    "comentarios": "",
                    "produto": produto,
                    "status": status,
                    "data_criacao": criado,
                    "data_fechamento": None,
                }
                ingestion_service.process_ticket_data(db, ticket_data)
                processed += 1

                if processed % 200 == 0:
                    logger.info("Processados %d tickets...", processed)

        sync_ticket_scope(db, allowed_keys)
        db.commit()
        logger.info("Importação IA concluída. Total processado=%d", processed)

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
