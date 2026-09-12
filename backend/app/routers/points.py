from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from app.main import engine

router = APIRouter()

BASE_SELECT = """
    SELECT id, external_id, obra, fonte, provincia_texto, provincia_geom,
           lon, lat, coordenada_status, aashto_raw, aashto_normalizado, sucs,
           cor, colapsividade, subleito, is_vermelho, source_type, source_file,
           dentro_mancha_vigente
    FROM v_points_full
"""


def _build_filters(provincia, cor, aashto, sucs, dentro_mancha, source_type):
    clauses, params = [], {}
    if provincia:
        clauses.append("(provincia_geom = :provincia OR provincia_texto ILIKE :provincia_like)")
        params["provincia"] = provincia
        params["provincia_like"] = f"%{provincia}%"
    if cor:
        clauses.append("cor = :cor")
        params["cor"] = cor
    if aashto:
        clauses.append("aashto_normalizado = :aashto")
        params["aashto"] = aashto
    if sucs:
        clauses.append("sucs = :sucs")
        params["sucs"] = sucs
    if dentro_mancha is not None:
        clauses.append("dentro_mancha_vigente = :dentro_mancha")
        params["dentro_mancha"] = dentro_mancha
    if source_type:
        clauses.append("source_type = :source_type")
        params["source_type"] = source_type
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


@router.get("")
def list_points(
    provincia: Optional[str] = None,
    cor: Optional[str] = None,
    aashto: Optional[str] = None,
    sucs: Optional[str] = None,
    dentro_mancha: Optional[bool] = None,
    source_type: Optional[str] = None,
    limit: int = Query(200, le=2000),
    offset: int = 0,
):
    """Lista pontos com filtros combináveis. Todos os campos vêm do banco em tempo real."""
    where, params = _build_filters(provincia, cor, aashto, sucs, dentro_mancha, source_type)
    params.update({"limit": limit, "offset": offset})
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM v_points_full {where}"), params).scalar()
        rows = conn.execute(
            text(f"{BASE_SELECT} {where} ORDER BY id LIMIT :limit OFFSET :offset"), params
        ).mappings().all()
    return {"total": total, "limit": limit, "offset": offset, "results": [dict(r) for r in rows]}


@router.get("/geojson")
def points_geojson(
    provincia: Optional[str] = None,
    cor: Optional[str] = None,
    aashto: Optional[str] = None,
    sucs: Optional[str] = None,
    dentro_mancha: Optional[bool] = None,
    source_type: Optional[str] = None,
    incluir_suspeitas: bool = Query(False, description="Se true, inclui pontos com coordenada "
                                     "marcada como suspeita/fora dos limites de Angola (ver /api/quality)"),
    limit: int = Query(5000, le=10000),
):
    """Mesmos filtros de /api/points, retornando FeatureCollection para o mapa.
    Por padrão, exclui coordenadas suspeitas (fora dos limites plausíveis de
    Angola) para não distorcer a visualização — use incluir_suspeitas=true
    para auditá-las explicitamente."""
    where, params = _build_filters(provincia, cor, aashto, sucs, dentro_mancha, source_type)
    extra = "coordenada_status = 'valida'" if not incluir_suspeitas else "lat IS NOT NULL"
    where = f"{where} AND {extra}" if where else f"WHERE {extra}"
    params["limit"] = limit
    with engine.connect() as conn:
        rows = conn.execute(text(f"{BASE_SELECT} {where} LIMIT :limit"), params).mappings().all()
    features = []
    for r in rows:
        d = dict(r)
        lon, lat = d.pop("lon"), d.pop("lat")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {k: (str(v) if hasattr(v, 'hex') else v) for k, v in d.items()},
        })
    return {"type": "FeatureCollection", "features": features}


@router.get("/{point_id}")
def get_point(point_id: str):
    """Dossiê completo de um ponto — usado pelo painel de investigação."""
    with engine.connect() as conn:
        row = conn.execute(
            text(f"{BASE_SELECT} WHERE id = :id"), {"id": point_id}
        ).mappings().first()
        history = conn.execute(
            text("SELECT campo, valor_anterior, valor_novo, autor, justificativa, data "
                 "FROM classification_history WHERE point_id = :id ORDER BY data DESC"),
            {"id": point_id},
        ).mappings().all()
    if not row:
        raise HTTPException(status_code=404, detail="Ponto não encontrado na base atualmente carregada.")
    result = dict(row)
    result["historico_reclassificacao"] = [dict(h) for h in history]
    return result
