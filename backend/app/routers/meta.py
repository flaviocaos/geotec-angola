from fastapi import APIRouter
from sqlalchemy import text
from app.main import engine

router = APIRouter()


@router.get("/")
def root():
    return {
        "name": "GeoTec Angola API",
        "status": "online",
        "docs": "/docs",
    }


@router.get("/api/health")
def health():
    with engine.connect() as conn:
        version = conn.execute(text("SELECT PostGIS_Version()")).scalar()
        n_points = conn.execute(text("SELECT count(*) FROM points")).scalar()
    return {"database": "ok", "postgis_version": version, "total_pontos": n_points}
