import logging
import time
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class AnalyticsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        user = getattr(request.state, "user", None) or {}
        logger.info("http_request", extra={
            "ctx_method": request.method,
            "ctx_url": str(request.url),
            "ctx_status": response.status_code,
            "ctx_duration_ms": duration_ms,
            "ctx_userEmail": user.get("email"),
        })
        return response
