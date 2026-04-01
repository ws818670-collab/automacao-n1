from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from api.middleware import RequestMiddleware
from api.routes import router
from models.database import init_db
from utils.config import get_settings
from utils.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import logging
    from utils.config import get_settings as _gs

    _s = _gs()
    _log = logging.getLogger(__name__)
    _log.info(
        "LLM provider ativo: %s | modelo: %s | llm_disponivel: %s",
        _s.llm_provider,
        _s.gemini_model if _s.llm_provider == "gemini" else _s.llm_model,
        bool(_s.gemini_api_key_value()) if _s.llm_provider == "gemini" else bool(_s.openai_api_key_value()),
    )
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(RequestMiddleware)
app.include_router(router, prefix="/v1")
Instrumentator().instrument(app).expose(app, endpoint="/metrics")
