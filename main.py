"""
sintetizador-api · FastAPI
--------------------------------------------------------------
  GET  /health
  POST /synthesize  body={folio, force=false} → unifica el estudio
  GET  /synthesis/{folio}                  → última síntesis cacheada
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import settings  # noqa: E402
from src.core.structured_logging import configure_logging  # noqa: E402
from src.database.cloudsql_handler import CloudSQLHandler  # noqa: E402
from src.middleware.analytics import AnalyticsMiddleware  # noqa: E402
from src.middleware.oauth import GoogleOAuthMiddleware  # noqa: E402
from src.services.synthesizer import Synthesizer  # noqa: E402
from src.utils.responses import error_response, success_response  # noqa: E402

configure_logging()
logger = logging.getLogger(__name__)

db: Optional[CloudSQLHandler] = None
synthesizer: Optional[Synthesizer] = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global db, synthesizer
    logger.info("Starting sintetizador-api...")
    db = CloudSQLHandler()
    try:
        await db.initialize()
    except Exception as exc:  # noqa: BLE001
        logger.warning("CloudSQL init failed: %s", exc)
    synthesizer = Synthesizer()
    yield
    if db:
        await db.close()


app = FastAPI(
    title="sintetizador-api",
    description="Síntesis del estudio hipotecario en grafo de la propiedad.",
    version=settings.SERVICE_VERSION,
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.ALLOWED_ORIGINS, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])
app.add_middleware(AnalyticsMiddleware)
app.add_middleware(GoogleOAuthMiddleware)


class SynthesizeRequest(BaseModel):
    folio: str
    force: bool = Field(default=False, description="Recalcular aunque haya caché")


@app.get("/health")
async def health():
    db_ok = await db.health_check() if db else False
    return success_response(data={"service": settings.SERVICE_NAME, "database": "ok" if db_ok else "error"})


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    if not synthesizer or not db:
        return error_response("Servicio no listo", code="NOT_READY", status_code=503)

    if not req.force:
        cached = await db.get_cached_synthesis(req.folio)
        if cached and not cached.get("requiere_reproceso"):
            return success_response(
                data={"folio": req.folio, "version": cached["version"], "cached": True, **(cached["datos"] or {})},
                message="Síntesis recuperada de caché.",
            )

    extracciones = await db.fetch_estudio_extracciones(req.folio)
    if not extracciones:
        return error_response(f"Estudio {req.folio} sin documentos.", code="NO_EXTRACTIONS", status_code=404)

    grafo = synthesizer.synthesize(req.folio, extracciones)
    version = await db.save_synthesis(req.folio, grafo)

    return success_response(
        data={"folio": req.folio, "version": version, "cached": False, **grafo},
        message=f"Síntesis del estudio {req.folio} (v{version}).",
    )


@app.get("/synthesis/{folio}")
async def get_synthesis(folio: str):
    if not db:
        return error_response("DB no listo", code="NOT_READY", status_code=503)
    cached = await db.get_cached_synthesis(folio)
    if not cached:
        return error_response(f"No hay síntesis para {folio}", code="NOT_FOUND", status_code=404)
    return success_response(data={"folio": folio, "version": cached["version"], "cached": True, **(cached["datos"] or {})})
