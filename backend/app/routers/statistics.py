from typing import Optional
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from scipy.stats import chi2_contingency
from app.main import engine

router = APIRouter()

ALLOWED_FIELDS = {
    "cor": "c.cor",
    "aashto": "c.aashto_normalizado",
    "sucs": "c.sucs",
    "colapsividade": "c.colapsividade",
    "subleito": "c.subleito",
    "provincia": "au.name",
    "fonte": "p.fonte",
    "dentro_mancha": "vpf.dentro_mancha_vigente::text",
}


def _counts(conn, sql_field, table="points p JOIN classifications c ON c.point_id = p.id "
                                     "LEFT JOIN administrative_units au ON au.id = p.administrative_unit_id"):
    rows = conn.execute(text(f"""
        SELECT COALESCE({sql_field}::text, 'Não informado') AS categoria, count(*) AS n
        FROM {table}
        GROUP BY 1 ORDER BY 2 DESC
    """)).all()
    return {r.categoria: r.n for r in rows}


@router.get("/overview")
def overview():
    """Distribuições calculadas em tempo real a partir do banco (não hardcoded)."""
    with engine.connect() as conn:
        n_total = conn.execute(text("SELECT count(*) FROM points")).scalar()
        return {
            "n_total_registros": n_total,
            "cor": _counts(conn, ALLOWED_FIELDS["cor"]),
            "aashto": _counts(conn, ALLOWED_FIELDS["aashto"]),
            "sucs": _counts(conn, ALLOWED_FIELDS["sucs"]),
            "colapsividade": _counts(conn, ALLOWED_FIELDS["colapsividade"]),
            "subleito": _counts(conn, ALLOWED_FIELDS["subleito"]),
            "provincia": _counts(conn, ALLOWED_FIELDS["provincia"]),
            "fonte": _counts(conn, ALLOWED_FIELDS["fonte"]),
        }


@router.get("/cross")
def cross_tabulation(field_a: str, field_b: str):
    """
    Tabela de contingência + teste qui-quadrado entre dois campos categóricos.
    Sempre reporta N total, N usado e N excluído (seção 32 da especificação).
    Campos permitidos: cor, aashto, sucs, colapsividade, subleito, provincia, fonte, dentro_mancha
    """
    if field_a not in ALLOWED_FIELDS or field_b not in ALLOWED_FIELDS:
        raise HTTPException(400, f"Campos permitidos: {list(ALLOWED_FIELDS.keys())}")

    col_a, col_b = ALLOWED_FIELDS[field_a], ALLOWED_FIELDS[field_b]
    with engine.connect() as conn:
        n_total = conn.execute(text("SELECT count(*) FROM points")).scalar()
        rows = conn.execute(text(f"""
            SELECT COALESCE({col_a}::text,'Não informado') AS a,
                   COALESCE({col_b}::text,'Não informado') AS b,
                   count(*) AS n
            FROM points p
            JOIN classifications c ON c.point_id = p.id
            LEFT JOIN administrative_units au ON au.id = p.administrative_unit_id
            LEFT JOIN v_points_full vpf ON vpf.id = p.id
            GROUP BY 1,2
        """)).all()

    cats_a = sorted({r.a for r in rows})
    cats_b = sorted({r.b for r in rows})
    table = {a: {b: 0 for b in cats_b} for a in cats_a}
    for r in rows:
        table[r.a][r.b] = r.n

    matrix = [[table[a][b] for b in cats_b] for a in cats_a]
    n_usado = sum(sum(row) for row in matrix)
    n_ambos_informados = sum(
        v for a, bs in table.items() if a != 'Não informado'
        for b, v in bs.items() if b != 'Não informado'
    )

    chi2_result = None
    if len(cats_a) > 1 and len(cats_b) > 1 and n_usado > 0:
        try:
            chi2, p, dof, _ = chi2_contingency(matrix)
            chi2_result = {"chi2": round(chi2, 4), "p_value": round(p, 6), "graus_liberdade": dof}
        except ValueError as e:
            chi2_result = {"erro": str(e)}

    return {
        "field_a": field_a, "field_b": field_b,
        "categorias_a": cats_a, "categorias_b": cats_b,
        "tabela_contingencia": table,
        "n_total_base": n_total,
        "n_usado_na_tabela": n_usado,
        "n_com_ambos_os_campos_informados": n_ambos_informados,
        "n_com_pelo_menos_um_campo_ausente": n_total - n_ambos_informados,
        "observacao": "'Não informado' é mantido como categoria explícita na tabela de contingência "
                      "(nenhum registro é descartado silenciosamente). O teste qui-quadrado, porém, "
                      "é sensível a essa categoria; para uma leitura mais estrita, considere apenas "
                      "n_com_ambos_os_campos_informados.",
        "qui_quadrado": chi2_result,
    }


@router.get("/confusion-matrix")
def confusion_matrix():
    """
    Matriz de confusão: classificação de cor (vermelho/não-vermelho) vs.
    situação espacial em relação à mancha vigente (seções 33-34).
    TP = vermelho dentro | FN = vermelho fora | FP = não-vermelho dentro | TN = não-vermelho fora
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
                count(*) FILTER (WHERE is_vermelho = true AND dentro_mancha_vigente = true) AS tp,
                count(*) FILTER (WHERE is_vermelho = true AND dentro_mancha_vigente = false) AS fn,
                count(*) FILTER (WHERE is_vermelho = false AND dentro_mancha_vigente = true) AS fp,
                count(*) FILTER (WHERE is_vermelho = false AND dentro_mancha_vigente = false) AS tn,
                count(*) FILTER (WHERE is_vermelho IS NULL) AS sem_classificacao_cor
            FROM v_points_full WHERE lat IS NOT NULL
        """)).mappings().first()

    tp, fn, fp, tn = row["tp"], row["fn"], row["fp"], row["tn"]
    n = tp + fn + fp + tn
    if n == 0:
        raise HTTPException(404, "Dado não disponível na base atualmente carregada.")

    accuracy = (tp + tn) / n
    sensitivity = tp / (tp + fn) if (tp + fn) else None
    specificity = tn / (tn + fp) if (tn + fp) else None
    precision = tp / (tp + fp) if (tp + fp) else None
    npv = tn / (tn + fn) if (tn + fn) else None
    f1 = (2 * precision * sensitivity / (precision + sensitivity)) if precision and sensitivity else None

    return {
        "descricao": "Calculado sobre pontos da planilha geotécnica com coordenada válida, "
                     "cruzados espacialmente com a mancha vigente. Distinto do conjunto curado "
                     "usado na reclassificação oficial do geólogo (ver /api/red-soil/reclassificacao).",
        "TP_vermelho_dentro": tp, "FN_vermelho_fora": fn,
        "FP_nao_vermelho_dentro": fp, "TN_nao_vermelho_fora": tn,
        "sem_classificacao_cor_excluidos": row["sem_classificacao_cor"],
        "N_usado": n,
        "acuracia": round(accuracy, 4),
        "sensibilidade": round(sensitivity, 4) if sensitivity is not None else None,
        "especificidade": round(specificity, 4) if specificity is not None else None,
        "precisao_ppv": round(precision, 4) if precision is not None else None,
        "npv": round(npv, 4) if npv is not None else None,
        "f1_score": round(f1, 4) if f1 is not None else None,
    }
