from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from app.main import engine

router = APIRouter()


@router.get("")
def investigate(
    lat: float = Query(..., description="Latitude WGS84"),
    lon: float = Query(..., description="Longitude WGS84"),
    radius_km: float = Query(20, le=200),
    n_nearest: int = Query(10, le=100),
):
    """
    Modo Investigação Geotécnica (seções 55-65). Dado qualquer coordenada,
    retorna o dossiê técnico da localização: unidade administrativa, situação
    em relação à mancha de solos vermelhos, resumo geotécnico dentro do raio
    e os N pontos mais próximos com distância real (PostGIS geography).
    """
    with engine.connect() as conn:
        # 1. unidade administrativa
        prov = conn.execute(text("""
            SELECT name FROM administrative_units
            WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon,:lat),4326))
            LIMIT 1
        """), {"lat": lat, "lon": lon}).scalar()

        # 2. situação da mancha vigente
        mancha = conn.execute(text("""
            SELECT
                ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)) AS dentro,
                ST_Distance(
                    geom::geography,
                    ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography
                ) / 1000.0 AS distancia_borda_km
            FROM red_soil_versions WHERE is_current = true
        """), {"lat": lat, "lon": lon}).mappings().first()

        # 3. resumo geotécnico dentro do raio (seção 62)
        resumo = conn.execute(text("""
            SELECT
                count(*) AS n_total,
                count(*) FILTER (WHERE cbr IS NOT NULL) AS n_com_ensaio,
                count(*) FILTER (WHERE is_vermelho = true) AS n_vermelhos,
                count(*) FILTER (WHERE is_vermelho = false) AS n_nao_vermelhos,
                count(*) FILTER (WHERE aashto_normalizado IS NULL) AS n_sem_aashto,
                count(*) FILTER (WHERE sucs IS NULL) AS n_sem_sucs,
                count(DISTINCT fonte) AS n_fontes_distintas
            FROM points p JOIN classifications c ON c.point_id = p.id
            WHERE ST_DWithin(
                p.geom::geography,
                ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,
                :radius_m
            )
        """), {"lat": lat, "lon": lon, "radius_m": radius_km * 1000}).mappings().first()

        # 4. pontos mais próximos com distância real
        nearest = conn.execute(text("""
            SELECT p.id, p.external_id, p.obra, p.fonte, c.cor, c.aashto_normalizado,
                   c.sucs, c.colapsividade,
                   round((ST_Distance(
                       p.geom::geography,
                       ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography
                   ) / 1000.0)::numeric, 2) AS distancia_km
            FROM points p JOIN classifications c ON c.point_id = p.id
            WHERE p.geom IS NOT NULL
            ORDER BY p.geom <-> ST_SetSRID(ST_MakePoint(:lon,:lat),4326)
            LIMIT :n
        """), {"lat": lat, "lon": lon, "n": n_nearest}).mappings().all()

    if not nearest:
        raise HTTPException(404, "Dado não disponível na base atualmente carregada.")

    # nível de confiança simples (seção 65) — baseado em densidade + presença de ensaio no raio
    n_total = resumo["n_total"]
    confianca = "Muito baixa"
    if n_total >= 20:
        confianca = "Alta" if resumo["n_com_ensaio"] / n_total > 0.5 else "Moderada"
    elif n_total >= 5:
        confianca = "Baixa" if resumo["n_com_ensaio"] > 0 else "Muito baixa"

    return {
        "coordenada": {"lat": lat, "lon": lon},
        "provincia": prov or "Não disponível na base atualmente carregada.",
        "mancha_solos_vermelhos": {
            "dentro": bool(mancha["dentro"]) if mancha else None,
            "distancia_ate_borda_km": round(mancha["distancia_borda_km"], 2) if mancha else None,
        },
        "resumo_no_raio": {"raio_km": radius_km, **dict(resumo)},
        "pontos_mais_proximos": [dict(r) for r in nearest],
        "confianca_estimada": confianca,
        "metodologia_confianca": "Baseada em densidade de pontos e presença de ensaio de laboratório "
                                  "dentro do raio consultado. Critério simplificado — não substitui "
                                  "investigação de campo específica.",
    }
