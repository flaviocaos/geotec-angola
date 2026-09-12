import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://geotec:geotec_dev_pw@localhost:5432/geotec_angola"
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

app = FastAPI(
    title="GeoTec Angola API",
    description="API da Plataforma de Inteligência Geotécnica de Angola. "
                 "Todos os valores são calculados dinamicamente a partir do banco "
                 "PostgreSQL/PostGIS — fonte única de verdade da plataforma.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajustar para o domínio real do frontend em produção
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import points, statistics, red_soil, administrative, investigation, quality, meta  # noqa: E402

app.include_router(meta.router, tags=["meta"])
app.include_router(points.router, prefix="/api/points", tags=["pontos"])
app.include_router(statistics.router, prefix="/api/statistics", tags=["estatisticas"])
app.include_router(red_soil.router, prefix="/api/red-soil", tags=["solos-vermelhos"])
app.include_router(administrative.router, prefix="/api/administrative-units", tags=["administrativo"])
app.include_router(investigation.router, prefix="/api/investigation", tags=["investigacao"])
app.include_router(quality.router, prefix="/api/quality", tags=["qualidade"])
