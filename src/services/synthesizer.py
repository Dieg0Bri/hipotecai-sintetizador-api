"""
Synthesizer · une extracciones de un estudio en un grafo del inmueble
--------------------------------------------------------------
Estructura del grafo (NetworkX DiGraph):

    estudio (folio)
      └── propiedad (rol_sii)
           ├── titularidad (CBR · cert_dominio_vigente)
           │     └── titular_actual (RUT, nombre)
           ├── gravamenes (CBR · cert_hipotecas_gravamenes)
           │     └── hipotecas[]
           ├── valoracion (SII · cert_avaluo_sii)
           ├── municipal (DOM · cert_municipal)
           ├── plano (cajetín · plano_propiedad)
           ├── normativa (plan_regulador)
           └── actos[] (escrituras: compraventa, hipoteca, alzamiento)

Cuando dos fuentes entregan valores distintos para un mismo campo, se
genera una **incongruencia** que el verificacion-legal-api lee.
"""
import logging
from typing import Any, Iterable

import networkx as nx

logger = logging.getLogger(__name__)


# Campos que se contrastan entre fuentes para detectar discrepancias.
CAMPOS_CONTRASTABLES = (
    "rol_sii", "rol_propiedad", "rol_avaluo",
    "direccion", "direccion_propiedad", "direccion_oficial",
    "titular_actual", "superficie_construida_m2", "superficie_total_m2", "comuna",
)


def _norm_rol(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().replace(" ", "")
    return s if s else None


def _coalesce(*values):
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


class Synthesizer:
    def synthesize(self, folio: str, extracciones: list[dict]) -> dict:
        """
        Construye el grafo + summary del estudio.
        `extracciones` viene de db.fetch_estudio_extracciones(folio).
        """
        g = nx.DiGraph()

        # Nodo raíz
        g.add_node(f"estudio:{folio}", label="Estudio", folio=folio, type="estudio")

        # Agrupar por schema
        por_schema: dict[str, list[dict]] = {}
        for ex in extracciones:
            schema = ex.get("schema_codigo") or "otro"
            por_schema.setdefault(schema, []).append(ex)

        # Identificar la propiedad (rol_sii) — buscar consistencia
        rol_unificado = self._unificar_rol(por_schema)
        propiedad_id = f"propiedad:{rol_unificado or folio}"
        g.add_node(propiedad_id, label="Propiedad", rol_sii=rol_unificado, type="propiedad")
        g.add_edge(f"estudio:{folio}", propiedad_id, rel="trata_de")

        # ─── Construir cada subárbol según el tipo de documento ───
        self._add_titularidad(g, propiedad_id, por_schema.get("cert_dominio_vigente", []))
        self._add_gravamenes(g, propiedad_id, por_schema.get("cert_hipotecas_gravamenes", []))
        self._add_valoracion(g, propiedad_id, por_schema.get("cert_avaluo_sii", []))
        self._add_municipal(g, propiedad_id, por_schema.get("cert_municipal", []))
        self._add_plano(g, propiedad_id, por_schema.get("plano_propiedad", []))
        self._add_normativa(g, propiedad_id, por_schema.get("plan_regulador", []))
        self._add_actos(g, propiedad_id, por_schema.get("escritura", []))

        # Detectar incongruencias inter-fuente
        incongruencias = self._detectar_incongruencias(por_schema, rol_unificado)

        # Métricas de completitud
        completeness = self._calcular_completeness(por_schema)

        # Serializar el grafo a JSON-friendly (node-link)
        grafo = nx.node_link_data(g)

        return {
            "folio": folio,
            "grafo": grafo,
            "incongruencias": incongruencias,
            "completeness": completeness,
            "fuentes": {schema: len(items) for schema, items in por_schema.items()},
            "version_schema": "v0",
        }

    # ─────────────────────────── builders ───────────────────────────

    def _unificar_rol(self, por_schema: dict[str, list[dict]]) -> str | None:
        """Busca el rol_sii en todas las fuentes y devuelve el más consistente."""
        candidatos = []
        for items in por_schema.values():
            for it in items:
                d = (it.get("datos") or {})
                rol = _coalesce(d.get("rol_sii"), d.get("rol_propiedad"), d.get("rol_avaluo"))
                if rol:
                    candidatos.append(_norm_rol(rol))
        if not candidatos:
            return None
        # Mode (rol más frecuente)
        from collections import Counter
        return Counter(candidatos).most_common(1)[0][0]

    def _add_titularidad(self, g: nx.DiGraph, parent: str, items: list[dict]):
        if not items:
            return
        d = items[0].get("datos") or {}
        node = "titularidad"
        g.add_node(node, label="Titularidad", source="cert_dominio_vigente", **{
            "titular_actual": d.get("titular_actual"),
            "titular_rut": d.get("titular_rut"),
            "foja": d.get("foja"),
            "numero_inscripcion": d.get("numero_inscripcion"),
            "anio_inscripcion": d.get("anio_inscripcion"),
            "cbr_emisor": d.get("cbr_emisor"),
            "fecha_emision": d.get("fecha_emision"),
        })
        g.add_edge(parent, node, rel="titularidad_actual")

    def _add_gravamenes(self, g: nx.DiGraph, parent: str, items: list[dict]):
        if not items:
            return
        d = items[0].get("datos") or {}
        node = "gravamenes"
        g.add_node(node, label="Gravámenes", source="cert_hipotecas_gravamenes", **{
            "libre_de_gravamenes": d.get("libre_de_gravamenes"),
            "fecha_emision": d.get("fecha_emision"),
            "n_hipotecas": len(d.get("hipotecas_vigentes") or []),
            "n_prohibiciones": len(d.get("prohibiciones") or []),
        })
        g.add_edge(parent, node, rel="gravamenes")

        for i, hip in enumerate(d.get("hipotecas_vigentes") or [], start=1):
            hid = f"hipoteca:{i}"
            g.add_node(hid, label="Hipoteca", **{**hip, "type": "hipoteca"})
            g.add_edge(node, hid, rel="hipoteca")

    def _add_valoracion(self, g: nx.DiGraph, parent: str, items: list[dict]):
        if not items:
            return
        d = items[0].get("datos") or {}
        node = "valoracion"
        g.add_node(node, label="Valoración SII", source="cert_avaluo_sii", **{
            "avaluo_total_clp": d.get("avaluo_total_clp"),
            "avaluo_terreno_clp": d.get("avaluo_terreno_clp"),
            "avaluo_construccion_clp": d.get("avaluo_construccion_clp"),
            "superficie_terreno_m2": d.get("superficie_terreno_m2"),
            "superficie_construida_m2": d.get("superficie_construida_m2"),
            "destino": d.get("destino"),
            "exento_iva": d.get("exento_iva"),
        })
        g.add_edge(parent, node, rel="valoracion_fiscal")

    def _add_municipal(self, g: nx.DiGraph, parent: str, items: list[dict]):
        if not items:
            return
        d = items[0].get("datos") or {}
        node = "municipal"
        g.add_node(node, label="Datos municipales", source="cert_municipal", **{
            "municipalidad": d.get("municipalidad"),
            "numero_municipal": d.get("numero_municipal"),
            "no_expropiacion": d.get("no_expropiacion"),
            "recepcion_final": d.get("recepcion_final"),
            "permiso_edificacion": d.get("permiso_edificacion"),
        })
        g.add_edge(parent, node, rel="estado_municipal")

    def _add_plano(self, g: nx.DiGraph, parent: str, items: list[dict]):
        if not items:
            return
        d = items[0].get("datos") or {}
        node = "plano"
        g.add_node(node, label="Plano", source="plano_propiedad", **{
            "tipo_plano": d.get("tipo_plano"),
            "superficie_total_m2": d.get("superficie_total_m2"),
            "superficie_construida_m2": d.get("superficie_construida_m2"),
            "deslindes": d.get("deslindes"),
            "profesional": d.get("profesional"),
            "fecha_plano": d.get("fecha_plano"),
        })
        g.add_edge(parent, node, rel="plano")

    def _add_normativa(self, g: nx.DiGraph, parent: str, items: list[dict]):
        if not items:
            return
        d = items[0].get("datos") or {}
        node = "normativa"
        g.add_node(node, label="Plan regulador", source="plan_regulador", **{
            "comuna": d.get("comuna"),
            "zonificacion": d.get("zonificacion"),
            "usos_permitidos": d.get("usos_permitidos"),
            "altura_maxima": d.get("altura_maxima"),
            "coef_constructibilidad": d.get("coef_constructibilidad"),
            "coef_ocupacion_suelo": d.get("coef_ocupacion_suelo"),
            "densidad_max": d.get("densidad_max"),
        })
        g.add_edge(parent, node, rel="normativa_aplicable")

    def _add_actos(self, g: nx.DiGraph, parent: str, items: list[dict]):
        for i, it in enumerate(items, start=1):
            d = it.get("datos") or {}
            aid = f"acto:{i}"
            g.add_node(aid, label="Escritura", source="escritura", type="acto", **{
                "tipo_acto": d.get("tipo_acto"),
                "fecha_otorgamiento": d.get("fecha_otorgamiento"),
                "notario_nombre": d.get("notario_nombre"),
                "repertorio": d.get("repertorio"),
                "vendedores": d.get("vendedores") or [],
                "compradores": d.get("compradores") or [],
                "precio_clp": d.get("precio_clp"),
                "precio_uf": d.get("precio_uf"),
            })
            g.add_edge(parent, aid, rel="acto_juridico")

    # ─────────────── incongruencias ───────────────

    def _detectar_incongruencias(self, por_schema: dict[str, list[dict]], rol_canon: str | None) -> list[dict]:
        """Compara el mismo campo entre fuentes; si difiere → incongruencia."""
        hallazgos: list[dict] = []

        # Roles distintos
        rols = set()
        for schema, items in por_schema.items():
            for it in items:
                d = it.get("datos") or {}
                rol = _coalesce(d.get("rol_sii"), d.get("rol_propiedad"), d.get("rol_avaluo"))
                if rol:
                    rols.add((schema, _norm_rol(rol)))
        rol_values = {r[1] for r in rols}
        if len(rol_values) > 1:
            hallazgos.append({
                "campo": "rol_sii",
                "tipo": "discrepancia_inter_fuente",
                "valores": [{"fuente": s, "valor": v} for s, v in rols],
                "severidad": "alta",
                "rol_canonico": rol_canon,
            })

        # Direcciones distintas
        direcciones = []
        for schema, items in por_schema.items():
            for it in items:
                d = it.get("datos") or {}
                addr = _coalesce(d.get("direccion"), d.get("direccion_propiedad"), d.get("direccion_oficial"))
                if addr:
                    direcciones.append((schema, str(addr).strip().lower()))
        if len({a for _, a in direcciones}) > 1:
            hallazgos.append({
                "campo": "direccion",
                "tipo": "discrepancia_inter_fuente",
                "valores": [{"fuente": s, "valor": v} for s, v in direcciones],
                "severidad": "media",
            })

        # Superficie construida (plano vs SII)
        sii_sup = self._extract_first(por_schema.get("cert_avaluo_sii", []), "superficie_construida_m2")
        plano_sup = self._extract_first(por_schema.get("plano_propiedad", []), "superficie_construida_m2")
        if sii_sup and plano_sup and abs(float(sii_sup) - float(plano_sup)) > 1.0:
            hallazgos.append({
                "campo": "superficie_construida_m2",
                "tipo": "discrepancia_dimensional",
                "valores": [
                    {"fuente": "cert_avaluo_sii", "valor": sii_sup},
                    {"fuente": "plano_propiedad", "valor": plano_sup},
                ],
                "severidad": "media",
                "diferencia_m2": round(abs(float(sii_sup) - float(plano_sup)), 2),
            })

        return hallazgos

    @staticmethod
    def _extract_first(items: list[dict], key: str):
        for it in items:
            v = (it.get("datos") or {}).get(key)
            if v not in (None, "", [], {}):
                return v
        return None

    # ─────────────── completeness ───────────────

    @staticmethod
    def _calcular_completeness(por_schema: dict[str, list[dict]]) -> dict:
        """Cobertura de fuentes: cuántos de los 7 schemas legales están presentes."""
        TODOS = (
            "escritura", "cert_dominio_vigente", "cert_hipotecas_gravamenes",
            "cert_avaluo_sii", "cert_municipal", "plano_propiedad", "plan_regulador",
        )
        presentes = [s for s in TODOS if por_schema.get(s)]
        return {
            "schemas_presentes": presentes,
            "schemas_faltantes": [s for s in TODOS if s not in presentes],
            "cobertura_pct": round(100.0 * len(presentes) / len(TODOS), 1),
        }
