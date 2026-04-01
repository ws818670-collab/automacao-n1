"""
Importa a base de conhecimento curada (arquivo .xlsx) para o banco de dados.

Uso:
  python tools/import_curated_xlsx.py
  python tools/import_curated_xlsx.py --xlsx "C:/caminho/para/Base de conhecimento.xlsx"
  python tools/import_curated_xlsx.py --batch-size 50

O script:
  1. Lê todas as chaves Jira do Excel curado
  2. Busca os dados completos no Jira em lotes (JQL: key in (...))
  3. Processa e ingere cada ticket (embedding + análise)
  4. Remove do banco qualquer ticket que NÃO esteja na lista curada
"""

import argparse
import logging
import sys
from pathlib import Path

import openpyxl

# Permite executar via "python tools/import_curated_xlsx.py"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from embeddings.service import EmbeddingService
from ingestion.service import IngestionService
from jira.client import JiraClient, normalize_issue
from models.database import SessionLocal, init_db
from models.repositories import sync_ticket_scope
from utils.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_XLSX = (
    Path(__file__).resolve().parents[2] / "Base de conhecimento.xlsx"
)


def read_curated_keys(xlsx_path: Path) -> list[str]:
    """Lê a coluna 'Chave da item' (primeira coluna) e retorna as chaves válidas."""
    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    ws = wb.active
    keys: list[str] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        value = row[0]
        if value and isinstance(value, str) and value.strip():
            keys.append(value.strip())
    wb.close()
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa base curada em XLSX para o banco de dados de conhecimento."
    )
    parser.add_argument(
        "--xlsx",
        default=str(DEFAULT_XLSX),
        help=f"Caminho para o arquivo Excel curado (padrão: {DEFAULT_XLSX})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Quantidade de chaves por lote JQL (padrão: 100)",
    )
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        logger.error("Arquivo não encontrado: %s", xlsx_path)
        sys.exit(1)

    settings = get_settings()
    init_db()
    curated_keys = read_curated_keys(xlsx_path)
    if not curated_keys:
        logger.error("Nenhuma chave encontrada no arquivo Excel.")
        sys.exit(1)
    logger.info("Total de chaves curadas: %d", len(curated_keys))

    jira_client = JiraClient()
    embedding_service = EmbeddingService()
    ingestion_service = IngestionService(jira_client, embedding_service)

    db = SessionLocal()
    total_processed = 0
    total_not_found = 0
    batch_size = args.batch_size
    num_batches = (len(curated_keys) + batch_size - 1) // batch_size

    try:
        for batch_num, batch_start in enumerate(range(0, len(curated_keys), batch_size), start=1):
            batch = curated_keys[batch_start : batch_start + batch_size]
            keys_str = ", ".join(batch)
            jql = f"key in ({keys_str})"

            logger.info(
                "[Lote %d/%d] Buscando %d tickets (índices %d–%d)...",
                batch_num,
                num_batches,
                len(batch),
                batch_start + 1,
                batch_start + len(batch),
            )

            try:
                issues = jira_client.search_issues(jql, max_results=0)
            except Exception as exc:
                logger.error("Erro ao buscar lote %d: %s", batch_num, exc)
                continue

            if len(issues) < len(batch):
                not_found = len(batch) - len(issues)
                total_not_found += not_found
                logger.warning(
                    "[Lote %d/%d] %d ticket(s) não encontrado(s) no Jira.",
                    batch_num,
                    num_batches,
                    not_found,
                )

            for issue in issues:
                normalized = normalize_issue(issue)
                ingestion_service.process_ticket_data(db, normalized)
                total_processed += 1

            db.flush()
            logger.info(
                "[Lote %d/%d] Concluído. Acumulado: %d tickets processados.",
                batch_num,
                num_batches,
                total_processed,
            )

        # Remove do banco qualquer ticket fora da lista curada
        logger.info("Sincronizando base: removendo tickets fora da curadoria...")
        sync_ticket_scope(db, set(curated_keys))

        db.commit()
        logger.info(
            "Importação finalizada! Processados: %d | Não encontrados no Jira: %d",
            total_processed,
            total_not_found,
        )

    except Exception as exc:
        db.rollback()
        logger.error("Erro durante a importação: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
