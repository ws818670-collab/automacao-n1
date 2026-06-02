import sys
sys.path.insert(0, '.')
from contextlib import contextmanager
from jira.client import JiraClient
from llm.service import LLMService
from embeddings.service import EmbeddingService
from retrieval.service import RetrievalService
from ingestion.service import IngestionService
from vector.factory import build_vector_store
from models.database import SessionLocal, init_db
from utils.config import get_settings

ISSUE_KEY = 'JDMSN1-2709'

@contextmanager
def get_session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

try:
    settings = get_settings()
    init_db()

    client = JiraClient()
    llm = LLMService()
    embedding_service = EmbeddingService()
    vector_store = build_vector_store()
    retrieval_service = RetrievalService(vector_store=vector_store)
    ingestion_service = IngestionService(client, embedding_service, vector_store=vector_store)

    allowed_statuses = settings.knowledge_base_statuses_list()

    with get_session() as db:
        print('='*60)
        print(f'ANÁLISE COMPLETA: {ISSUE_KEY}')
        print('='*60)

        comment, tickets_ref, fallback = llm.generate_triage_comment(
            db,
            ISSUE_KEY,
            client,
            embedding_service,
            retrieval_service,
            allowed_statuses,
            post=True,
        )

        print(comment)
        print()
        print(f"Tickets referenciados: {tickets_ref}")
        print(f"Fallback usado: {fallback}")

except Exception as e:
    import traceback
    print(f'Erro: {e}')
    traceback.print_exc()
