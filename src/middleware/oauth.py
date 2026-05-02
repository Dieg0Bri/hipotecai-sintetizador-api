"""Same OAuth gateway middleware as clasificador-api/documentos-api."""
import base64
import json
import logging
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.config import settings

logger = logging.getLogger(__name__)
PUBLIC_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc")
TEST_USER = {"email": "test@hipotecai.cl", "sub": "test-id", "name": "Letrado", "email_verified": True}


class GoogleOAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable]):
        if any(request.url.path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)
        if settings.SKIP_AUTH or settings.ENVIRONMENT == "test":
            request.state.user = TEST_USER
            return await call_next(request)

        userinfo = request.headers.get("x-apigateway-api-userinfo")
        auth = request.headers.get("x-forwarded-authorization") or request.headers.get("authorization")
        if not userinfo and not auth:
            return JSONResponse(status_code=401, content={"status": "error", "code": "NO_AUTH", "message": "Auth requerida."})

        user = None
        if userinfo:
            try:
                user = json.loads(base64.b64decode(userinfo).decode())
            except Exception as exc:
                logger.warning("decode failed: %s", exc)

        if not user:
            return JSONResponse(status_code=401, content={"status": "error", "code": "NO_USER", "message": "Sin info."})

        request.state.user = user
        return await call_next(request)
