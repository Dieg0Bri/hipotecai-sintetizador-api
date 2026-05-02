"""
CloudSQLHandler — lee dt_extraccion del estudio, persiste el grafo
sintetizado en dt_sintetizador (versionado).
"""
import json
import logging
import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy import text

from src.core.config import settings

logger = logging.getLogger(__name__)


class CloudSQLHandler:
    def __init__(self):
        self.engine: Optional[AsyncEngine] = None
        self.session_factory = None

    def _build_url(self) -> str:
        if os.environ.get("K_SERVICE") and settings.INSTANCE_CONNECTION_NAME:
            return (
                f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}"
                f"@/{settings.DB_NAME}?host=/cloudsql/{settings.INSTANCE_CONNECTION_NAME}"
            )
        return (
            f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}"
            f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
        )

    async def initialize(self):
        self.engine = create_async_engine(self._build_url(), pool_pre_ping=True, pool_size=5)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def health_check(self) -> bool:
        if not self.engine:
            return False
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.error("health_check failed: %s", exc)
            return False

    async def fetch_estudio_extracciones(self, folio: str) -> list[dict]:
        sql = text(
            """
            SELECT a.id_archivo, a.nombre, a.gcs_path, cl.codigo AS schema_codigo,
                   ex.datos, ex.spans, ex.confianza, a.estado_revision
            FROM dt_estudio e
            JOIN dt_archivos a       ON a.id_estudio = e.id_estudio AND a.eliminado = FALSE
            LEFT JOIN dt_clasificaciones cl ON cl.id = a.id_clasificacion
            LEFT JOIN dt_extraccion ex     ON ex.id_archivo = a.id_archivo
            WHERE e.folio = :folio
            ORDER BY a.fecha_subida
            """
        )
        async with self.session_factory() as session:
            result = await session.execute(sql, {"folio": folio})
            rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def get_cached_synthesis(self, folio: str) -> dict | None:
        sql = text(
            """
            SELECT datos, version, requiere_reproceso
            FROM dt_sintetizador
            WHERE folio = :folio
            ORDER BY version DESC
            LIMIT 1
            """
        )
        async with self.session_factory() as session:
            row = (await session.execute(sql, {"folio": folio})).mappings().first()
        return dict(row) if row else None

    async def save_synthesis(self, folio: str, grafo: dict) -> int:
        sql = text(
            """
            INSERT INTO dt_sintetizador (folio, datos, version, requiere_reproceso, fecha)
            VALUES (
              :folio,
              CAST(:datos AS JSONB),
              COALESCE((SELECT MAX(version) FROM dt_sintetizador WHERE folio = :folio), 0) + 1,
              FALSE,
              NOW()
            )
            RETURNING version
            """
        )
        async with self.session_factory() as session:
            row = (await session.execute(sql, {"folio": folio, "datos": json.dumps(grafo)})).first()
            await session.commit()
        return row[0]

    async def close(self):
        if self.engine:
            await self.engine.dispose()
