# sintetizador-api

Servicio Python/FastAPI que **unifica todas las extracciones** de un estudio hipotecario en un único grafo de la propiedad (NetworkX DiGraph) y detecta incongruencias inter-fuente. Inspirado en el `sintetizador-api` de ISA1 (que une planos + RFQ + disposición + HDD), adaptado al dominio legal chileno.

## Endpoints

| Método | Ruta                       | Descripción |
|--------|----------------------------|-------------|
| GET    | `/health`                  | Health |
| POST   | `/synthesize`              | `{folio, force}` → genera (o recupera de caché) la síntesis del estudio |
| GET    | `/synthesis/{folio}`       | Última síntesis cacheada |

## Estructura del grafo

```
estudio (folio)
  └── propiedad (rol_sii unificado)
       ├── titularidad           ← cert_dominio_vigente (CBR)
       │     └── titular_actual
       ├── gravamenes            ← cert_hipotecas_gravamenes (CBR)
       │     └── hipoteca[]
       ├── valoracion            ← cert_avaluo_sii
       ├── municipal             ← cert_municipal
       ├── plano                 ← plano_propiedad
       ├── normativa             ← plan_regulador
       └── acto[]                ← escrituras (compraventa, hipoteca, alzamiento)
```

Serializado en formato JSON node-link de NetworkX, listo para visualización con Cytoscape o ReactFlow en el frontend.

## Detección de incongruencias

Al sintetizar, se comparan campos contrastables entre fuentes:

- **`rol_sii`** entre escritura, cert_dominio_vigente, cert_avaluo_sii, plano (severidad alta)
- **`direccion`** entre escritura, cert_dominio_vigente, cert_municipal (severidad media)
- **`superficie_construida_m2`** entre cert_avaluo_sii y plano_propiedad (severidad media, tolerancia 1 m²)

Las incongruencias se entregan en `data.incongruencias[]` y son consumidas por **verificacion-legal-api** para emitir `dt_hallazgos`.

## Versionado

Cada llamada a `/synthesize` con `force=true` genera una nueva versión en `dt_sintetizador`. La última se cachea y se devuelve en llamadas siguientes salvo que `requiere_reproceso=TRUE` (flag que actualizan los servicios upstream cuando hay nuevas extracciones).

## Desarrollo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8086
```
