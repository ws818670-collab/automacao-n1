import logging
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from utils.logging import set_correlation_id

logger = logging.getLogger(__name__)


class RequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = str(uuid4())
        set_correlation_id(correlation_id)
        started_at = perf_counter()

        try:
            response = await call_next(request)
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )

        response.headers["X-Correlation-ID"] = correlation_id
        set_correlation_id(None)
        return response