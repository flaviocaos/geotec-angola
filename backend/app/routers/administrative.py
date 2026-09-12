import json
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.main import engine

router = APIRouter()


@router.get("/geojson")
def provinces_geojson():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, name, code, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.01)) AS geom "
            "FROM administrative_units"
        )).mappings().all()
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"id": r["id"], "name": r["name"], "code": r["code"]},
            "geometry": json.loads(r["geom"]),
        } for r in rows]
    }


@router.get("/{unit_id}/summary")
def province_summary(unit_id: int):
    """Recalcula estatísticas geotécnicas para uma província específica (seção 42)."""
    with engine.connect() as conn:
        unit = conn.execute(text("SELECT name FROM administrative_units WHERE id=:id"), {"id": unit_id}).first()
        if not unit:
            raise HTTPException(404, "Província não encontrada.")
        stats = conn.execute(text("""
            SELECT
                count(*) AS n_pontos,
                count(*) FILTER (WHERE dentro_mancha_vigente) AS n_dentro_mancha,
                count(*) FILTER (WHERE is_vermelho) AS n_vermelhos,
                count(*) FILTER (WHERE aashto_normalizado IS NULL) AS n_sem_aashto,
                count(*) FILTER (WHERE sucs IS NULL) AS n_sem_sucs
            FROM v_points_full WHERE provincia_geom = :name
        """), {"name": unit.name}).mappings().first()
    return {"provincia": unit.name, **dict(stats)}
