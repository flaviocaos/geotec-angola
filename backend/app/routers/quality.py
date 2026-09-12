from fastapi import APIRouter
from sqlalchemy import text
from app.main import engine

router = APIRouter()


@router.get("")
def quality_report():
    """
    Painel de Qualidade da Base (seções 35-36). Cada número é contado
    diretamente do banco — nenhum score é fictício ou estimado.
    """
    with engine.connect() as conn:
        coord = conn.execute(text("""
            SELECT coordenada_status, count(*) AS n FROM points GROUP BY 1
        """)).mappings().all()

        dup = conn.execute(text("""
            SELECT count(*) AS n FROM (
                SELECT utm_e, utm_n FROM points
                WHERE utm_e IS NOT NULL AND utm_n IS NOT NULL
                GROUP BY utm_e, utm_n HAVING count(*) > 1
            ) t
        """)).scalar()

        ausencias = conn.execute(text("""
            SELECT
                count(*) FILTER (WHERE aashto_normalizado IS NULL) AS aashto_ausente,
                count(*) FILTER (WHERE sucs IS NULL) AS sucs_ausente,
                count(*) FILTER (WHERE colapsividade IS NULL) AS colapsividade_ausente,
                count(*) FILTER (WHERE subleito IS NULL) AS subleito_ausente,
                count(*) FILTER (WHERE cor IS NULL) AS cor_ausente
            FROM classifications
        """)).mappings().first()

        aashto_variantes = conn.execute(text("""
            SELECT count(DISTINCT aashto_raw) AS brutas,
                   count(DISTINCT aashto_normalizado) AS normalizadas
            FROM classifications WHERE aashto_raw IS NOT NULL
        """)).mappings().first()

        prov_variantes = conn.execute(text("""
            SELECT count(DISTINCT provincia_texto) AS n FROM points WHERE provincia_texto IS NOT NULL
        """)).scalar()

        sem_resolucao_espacial = conn.execute(text("""
            SELECT count(*) FROM points WHERE geom IS NOT NULL AND administrative_unit_id IS NULL
        """)).scalar()

        n_total = conn.execute(text("SELECT count(*) FROM points")).scalar()

    return {
        "n_total_registros": n_total,
        "cobertura_coordenadas": {r["coordenada_status"]: r["n"] for r in coord},
        "duplicidade_coordenada_utm": dup,
        "ausencias_por_campo": dict(ausencias),
        "aashto_variantes_grafia": dict(aashto_variantes),
        "provincia_variantes_texto_distintas": prov_variantes,
        "pontos_com_coordenada_fora_de_qualquer_provincia": sem_resolucao_espacial,
        "observacao": "Nenhuma inconsistência acima foi corrigida automaticamente. "
                      "Correções exigem validação humana e devem ser registradas em "
                      "classification_history, preservando o valor original.",
    }
