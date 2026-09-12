"""
GeoTec Angola — carga dos dados reais para PostgreSQL/PostGIS.

Lê o pacote de dados original e popula: data_sources, administrative_units,
points, classifications e red_soil_versions. Reaproveita a lógica de
parsing/conversão de scripts/ingest_geotec_angola.py.

Uso:
    export DATABASE_URL=postgresql://geotec:geotec_dev_pw@localhost:5432/geotec_angola
    python load_data.py
    # ou, para apontar para outro pacote de dados:
    python load_data.py /caminho/para/outro/Pacote_Dados_GeoTec_Angola_Projeto_Completo
"""
import os
import sys
import math
import pandas as pd
import pyproj
import shapefile
from lxml import etree
from shapely.geometry import Point, Polygon, MultiPolygon, shape
from shapely.ops import transform
from sqlalchemy import create_engine, text

NS = {'k': 'http://www.opengis.net/kml/2.2'}
UTM33S_TO_WGS84 = pyproj.Transformer.from_crs("EPSG:32733", "EPSG:4326", always_xy=True)
EQUAL_AREA = pyproj.Transformer.from_crs(
    "EPSG:4326",
    "+proj=aea +lat_1=-8 +lat_2=-18 +lat_0=-13 +lon_0=17.5 +datum=WGS84",
    always_xy=True,
).transform

DB_URL = os.environ.get("DATABASE_URL", "postgresql://geotec:geotec_dev_pw@localhost:5432/geotec_angola")


def parse_kml_polygons(path):
    tree = etree.parse(path)
    polys = []
    for pm in tree.findall('.//k:Placemark', NS):
        for poly_el in pm.findall('.//k:Polygon', NS):
            outer = poly_el.find('.//k:outerBoundaryIs/k:LinearRing/k:coordinates', NS)
            if outer is None:
                continue
            coords = [(float(c.split(',')[0]), float(c.split(',')[1])) for c in outer.text.strip().split()]
            if len(coords) >= 3:
                polys.append(Polygon(coords))
    return MultiPolygon(polys)


def load_planilha(base_dir):
    f = os.path.join(base_dir, "01_Bases_Tabulares", "PLANILHA_COMPLETA_VERIFICADA.xlsx")
    df = pd.read_excel(f, sheet_name="COM COORDENADAS", header=1)
    df = df.drop(index=[0, 1]).reset_index(drop=True)
    rename = {
        'FONTE': 'fonte', 'OBRA': 'obra', 'PROVÍNCIA': 'provincia',
        'IDENTIFICAÇÃO Nº': 'identificacao', 'COORDENADAS': 'zona_utm',
        'Unnamed: 7': 'utm_e', 'Unnamed: 8': 'utm_n',
        'PROFUNDIDADE (cm)': 'prof_de', 'Unnamed: 10': 'prof_ate',
        'GRANULOMETRIA POR PENEIRAMENTO % PASSANDO': 'pass_10',
        'Unnamed: 12': 'pass_40', 'Unnamed: 13': 'pass_200',
        'L. L.': 'll', 'I. P.': 'ip', 'I. G.': 'ig',
        'CLASSIFICAÇÃO H.R.B. - AASHTO': 'aashto_raw',
        'CLASSIFICAÇÃO TÁTIL-VISUAL': 'classificacao_tatil', 'COLORAÇÃO (COR)': 'cor',
        'CLASSIFICAÇÃO UNIFICADA - SUCS': 'sucs',
        'C.B.R (%)\n100%': 'cbr', 'EXPANSÃO (%)\n100%': 'expansao_pct',
        'EDOMÉTRCO': 'edometrico', 'CORTE DIRETO': 'corte_direto',
        'POTENCIAL DE COLPASIBILIDADE': 'colapsividade',
        'Comportamento geral como subleito': 'subleito',
    }
    df = df.rename(columns=rename)
    df = df[[c for c in rename.values() if c in df.columns]]

    def conv(row):
        e, n = _f(row['utm_e']), _f(row['utm_n'])
        if e is None or n is None:
            return pd.Series({'lat': None, 'lon': None, 'utm_invalido': False})
        try:
            lon, lat = UTM33S_TO_WGS84.transform(e, n)
            if not (math.isfinite(lon) and math.isfinite(lat)):
                # coordenada UTM fora de qualquer faixa plausível (ex.: erro de
                # digitação como um dígito extra) produz inf/nan na projeção —
                # tratada como suspeita, nunca como geometria inválida no banco
                return pd.Series({'lat': None, 'lon': None, 'utm_invalido': True})
            return pd.Series({'lat': lat, 'lon': lon, 'utm_invalido': False})
        except Exception:
            return pd.Series({'lat': None, 'lon': None, 'utm_invalido': True})

    df = pd.concat([df, df.apply(conv, axis=1)], axis=1)

    def status(row):
        if row.get('utm_invalido'):
            return 'suspeita_fora_angola'
        if pd.isna(row['lat']):
            return 'ausente'
        if not (-20 <= row['lat'] <= 0 and 10 <= row['lon'] <= 25):
            return 'suspeita_fora_angola'
        return 'valida'

    df['coordenada_status'] = df.apply(status, axis=1)

    def norm_aashto(v):
        if pd.isna(v):
            return None
        return str(v).strip().upper().replace('-', '.').replace(' ', '')

    df['aashto_normalizado'] = df['aashto_raw'].apply(norm_aashto)
    df['is_vermelho'] = df['cor'].apply(lambda c: None if pd.isna(c) else 'vermelho' in str(c).lower())
    return df


def main(base_dir):
    engine = create_engine(DB_URL)

    print("== 1. Fontes de dados ==")
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO data_sources (source_key, source_file, source_type, database_version, notes)
            VALUES
            ('planilha_geotecnica_ensaio', 'PLANILHA_COMPLETA_VERIFICADA.xlsx', 'ensaio', 'v1',
             '3.797 registros com ensaio geotécnico; fonte principal de AASHTO/SUCS/colapsividade'),
            ('provincias_angola', 'Provincias_Angola.shp', 'cartografia', 'v1', 'Limites administrativos oficiais (21 províncias)'),
            ('mancha_atual', '01_Mancha_Atual.kml', 'cartografia', 'v1', 'Mancha de solos vermelhos vigente'),
            ('mancha_revisada_proposta', '04_Mancha_Solos_Vermelhos_Revisada_Proposta.kml', 'derivado', 'v1', 'Proposta de revisão da mancha, ainda não oficial')
            ON CONFLICT (source_key) DO NOTHING;
        """))
        src_ids = dict(conn.execute(text("SELECT source_key, id FROM data_sources")).fetchall())

    print("== 2. Províncias ==")
    sf = shapefile.Reader(os.path.join(base_dir, "03_Limites_Administrativos", "Provincias_Angola.shp"))
    with engine.begin() as conn:
        for sr in sf.shapeRecords():
            geom = shape(sr.shape.__geo_interface__)
            if geom.geom_type == 'Polygon':
                geom = MultiPolygon([geom])
            rec = sr.record.as_dict()
            conn.execute(text("""
                INSERT INTO administrative_units (name, code, geom, source_id)
                VALUES (:name, :code, ST_SetSRID(ST_GeomFromText(:wkt), 4326), :source_id)
            """), {"name": rec.get("Nome_Prov"), "code": rec.get("Cod_Prov"),
                   "wkt": geom.wkt, "source_id": src_ids['provincias_angola']})
    print(f"   {len(sf.shapeRecords())} províncias inseridas")

    print("== 3. Mancha de solos vermelhos (vigente + revisada) ==")
    mancha_atual = parse_kml_polygons(os.path.join(base_dir, "07_Revisao_Mancha_100926", "01_Mancha_Atual.kml"))
    mancha_revisada = parse_kml_polygons(os.path.join(base_dir, "07_Revisao_Mancha_100926", "04_Mancha_Solos_Vermelhos_Revisada_Proposta.kml"))
    area_atual = transform(EQUAL_AREA, mancha_atual).area / 1e6
    area_revisada = transform(EQUAL_AREA, mancha_revisada).area / 1e6
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO red_soil_versions (version_label, status, geom, area_km2, methodology, source_id, is_current)
            VALUES ('VIGENTE', 'OFICIAL', ST_SetSRID(ST_GeomFromText(:wkt), 4326), :area, 'Delimitação cartográfica do projeto', :sid, true)
        """), {"wkt": mancha_atual.wkt, "area": area_atual, "sid": src_ids['mancha_atual']})
        conn.execute(text("""
            INSERT INTO red_soil_versions (version_label, status, geom, area_km2, methodology, source_id, is_current)
            VALUES ('REVISADA_PROPOSTA', 'EM_ANALISE', ST_SetSRID(ST_GeomFromText(:wkt), 4326), :area, 'Proposta de revisão 10/09/2026 — expansão/retração prioritária', :sid, false)
        """), {"wkt": mancha_revisada.wkt, "area": area_revisada, "sid": src_ids['mancha_revisada_proposta']})
    print(f"   vigente={area_atual:.1f} km² | revisada_proposta={area_revisada:.1f} km²")

    print("== 3b. Áreas de expansão/retração propostas ==")
    change_files = {
        "expansao_prioritaria": "02_Areas_Propostas_Expansao_Prioritaria.kml",
        "expansao_sob_revisao": "02B_Areas_Expansao_Sob_Revisao.kml",
        "retracao_prioritaria": "03_Areas_Propostas_Retracao_Prioritaria.kml",
        "interna_sob_revisao": "03B_Areas_Internas_Sob_Revisao.kml",
    }
    with engine.begin() as conn:
        v_from = conn.execute(text(
            "SELECT id FROM red_soil_versions WHERE version_label='VIGENTE'")).scalar()
        v_to = conn.execute(text(
            "SELECT id FROM red_soil_versions WHERE version_label='REVISADA_PROPOSTA'")).scalar()
        total_areas = 0
        for tipo, fname in change_files.items():
            path = os.path.join(base_dir, "07_Revisao_Mancha_100926", fname)
            mp = parse_kml_polygons(path)
            for poly in mp.geoms:
                area_km2 = transform(EQUAL_AREA, poly).area / 1e6
                conn.execute(text("""
                    INSERT INTO red_soil_change_areas (version_from_id, version_to_id, tipo, geom, area_km2)
                    VALUES (:vf, :vt, :tipo, ST_SetSRID(ST_GeomFromText(:wkt), 4326), :area)
                """), {"vf": v_from, "vt": v_to, "tipo": tipo, "wkt": poly.wkt, "area": area_km2})
                total_areas += 1
    print(f"   {total_areas} polígonos de mudança inseridos")

    print("== 4. Pontos + classificações ==")
    df = load_planilha(base_dir)
    with engine.begin() as conn:
        source_id = src_ids['planilha_geotecnica_ensaio']
        inserted = 0
        for _, row in df.iterrows():
            geom_sql = "NULL"
            params_geom = {}
            if pd.notna(row['lat']) and pd.notna(row['lon']):
                geom_sql = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
                params_geom = {"lon": float(row['lon']), "lat": float(row['lat'])}

            res = conn.execute(text(f"""
                INSERT INTO points (external_id, obra, fonte, provincia_texto, geom,
                                     utm_zona, utm_e, utm_n, coordenada_status, source_id)
                VALUES (:external_id, :obra, :fonte, :provincia, {geom_sql},
                        :zona, :utm_e, :utm_n, :status, :source_id)
                RETURNING id
            """), {
                "external_id": row.get('identificacao'), "obra": row.get('obra'),
                "fonte": row.get('fonte'), "provincia": row.get('provincia'),
                "zona": row.get('zona_utm'),
                "utm_e": _f(row.get('utm_e')),
                "utm_n": _f(row.get('utm_n')),
                "status": row['coordenada_status'], "source_id": source_id,
                **params_geom
            })
            point_id = res.scalar()

            conn.execute(text("""
                INSERT INTO classifications (point_id, prof_de_cm, prof_ate_cm, pass_10, pass_40, pass_200,
                    ll, ip, ig, aashto_raw, aashto_normalizado, classificacao_tatil, cor, sucs,
                    cbr, expansao_pct, edometrico, corte_direto, colapsividade, subleito, is_vermelho)
                VALUES (:point_id, :prof_de, :prof_ate, :pass_10, :pass_40, :pass_200,
                    :ll, :ip, :ig, :aashto_raw, :aashto_norm, :tatil, :cor, :sucs,
                    :cbr, :expansao, :edometrico, :corte, :colaps, :subleito, :vermelho)
            """), {
                "point_id": point_id,
                "prof_de": _f(row.get('prof_de')), "prof_ate": _f(row.get('prof_ate')),
                "pass_10": _f(row.get('pass_10')), "pass_40": _f(row.get('pass_40')), "pass_200": _f(row.get('pass_200')),
                "ll": _s(row.get('ll')), "ip": _s(row.get('ip')), "ig": _s(row.get('ig')),
                "aashto_raw": _s(row.get('aashto_raw')), "aashto_norm": _s(row.get('aashto_normalizado')),
                "tatil": _s(row.get('classificacao_tatil')), "cor": _s(row.get('cor')), "sucs": _s(row.get('sucs')),
                "cbr": _f(row.get('cbr')), "expansao": _f(row.get('expansao_pct')),
                "edometrico": _s(row.get('edometrico')), "corte": _s(row.get('corte_direto')),
                "colaps": _s(row.get('colapsividade')), "subleito": _s(row.get('subleito')),
                "vermelho": bool(row['is_vermelho']) if pd.notna(row['is_vermelho']) else None,
            })
            inserted += 1
    print(f"   {inserted} pontos + classificações inseridos")

    print("== 5. Resolvendo província por geometria (join espacial) ==")
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE points p SET administrative_unit_id = au.id
            FROM administrative_units au
            WHERE p.geom IS NOT NULL AND ST_Contains(au.geom, p.geom)
        """))
    print("   feito")

    print("\nCarga concluída.")


def _f(v):
    if pd.isna(v):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        pass
    # alguns registros usam vírgula como separador decimal (ex.: '785580,00')
    s = str(v).strip()
    try:
        if ',' in s and '.' not in s:
            return float(s.replace(',', '.'))
        return float(s.replace(',', ''))
    except (ValueError, TypeError):
        # valor não numérico presente na base bruta (ex.: '-', 'NL', 'NP') —
        # tratado como ausente, nunca convertido silenciosamente para 0
        return None


def _s(v):
    return str(v) if pd.notna(v) else None


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "raw", "Pacote_Dados_GeoTec_Angola_Projeto_Completo"
    )
    main(base)
