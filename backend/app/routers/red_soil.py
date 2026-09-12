from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.main import engine

router = APIRouter()


@router.get("/versions")
def list_versions():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, version_label, status, area_km2, methodology, is_current, created_at
            FROM red_soil_versions ORDER BY created_at
        """)).mappings().all()
    return [dict(r) for r in rows]


@router.get("/versions/{version_id}/geojson")
def version_geojson(version_id: int):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT version_label, status, area_km2, ST_AsGeoJSON(geom) AS geom
            FROM red_soil_versions WHERE id = :id
        """), {"id": version_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Versão não encontrada na base atualmente carregada.")
    import json
    return {
        "type": "Feature",
        "properties": {"version_label": row["version_label"], "status": row["status"], "area_km2": row["area_km2"]},
        "geometry": json.loads(row["geom"]),
    }


@router.get("/comparison")
def comparison():
    """Área atual x revisada, variação e saldo — sempre calculado via ST_Area, nunca hardcoded."""
    with engine.connect() as conn:
        atual = conn.execute(text(
            "SELECT area_km2 FROM red_soil_versions WHERE is_current = true")).scalar()
        revisada = conn.execute(text(
            "SELECT area_km2 FROM red_soil_versions WHERE version_label = 'REVISADA_PROPOSTA'")).scalar()
        changes = conn.execute(text("""
            SELECT tipo, count(*) AS n_zonas, round(sum(area_km2)::numeric, 1) AS area_km2
            FROM red_soil_change_areas GROUP BY tipo
        """)).mappings().all()
    if atual is None or revisada is None:
        raise HTTPException(404, "Dado não disponível na base atualmente carregada.")
    variacao = revisada - atual
    return {
        "area_atual_km2": round(atual, 1),
        "area_revisada_proposta_km2": round(revisada, 1),
        "variacao_liquida_km2": round(variacao, 1),
        "variacao_liquida_pct": round(variacao / atual * 100, 2),
        "zonas_de_mudanca": [dict(c) for c in changes],
    }


@router.get("/change-areas/geojson")
def change_areas_geojson(tipo: str = None):
    where = "WHERE tipo = :tipo" if tipo else ""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, tipo, area_km2, status, ST_AsGeoJSON(geom) AS geom
            FROM red_soil_change_areas {where}
        """), {"tipo": tipo} if tipo else {}).mappings().all()
    import json
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"id": r["id"], "tipo": r["tipo"], "area_km2": r["area_km2"], "status": r["status"]},
            "geometry": json.loads(r["geom"]),
        } for r in rows]
    }
