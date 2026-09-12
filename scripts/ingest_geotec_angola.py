"""
GeoTec Angola — pipeline de ingestão e cálculo dos indicadores do dashboard.

Reproduz, a partir do pacote de dados original
(Pacote_Dados_GeoTec_Angola_Projeto_Completo), exatamente os números
exibidos em geotec_angola_dashboard.html. Nenhum valor é inventado:
tudo é lido, convertido de coordenadas e calculado geometricamente aqui.

Requisitos: pandas, openpyxl, shapely, pyproj, pyshp, lxml
    pip install pandas openpyxl shapely pyproj pyshp lxml

Uso:
    python ingest_geotec_angola.py /caminho/para/Pacote_Dados_GeoTec_Angola_Projeto_Completo
"""
import sys
import json
import os
import pandas as pd
import pyproj
import shapefile
from lxml import etree
from shapely.geometry import Point, Polygon, MultiPolygon, mapping, shape
from shapely.ops import transform

NS = {'k': 'http://www.opengis.net/kml/2.2'}
UTM33S_TO_WGS84 = pyproj.Transformer.from_crs("EPSG:32733", "EPSG:4326", always_xy=True)
EQUAL_AREA_ANGOLA = pyproj.Transformer.from_crs(
    "EPSG:4326",
    "+proj=aea +lat_1=-8 +lat_2=-18 +lat_0=-13 +lon_0=17.5 +datum=WGS84",
    always_xy=True,
).transform


def parse_kml_polygons(path):
    """Extrai todos os polígonos (outerBoundaryIs) de um KML em um MultiPolygon lon/lat."""
    tree = etree.parse(path)
    polys = []
    for pm in tree.findall('.//k:Placemark', NS):
        for poly_el in pm.findall('.//k:Polygon', NS):
            outer = poly_el.find('.//k:outerBoundaryIs/k:LinearRing/k:coordinates', NS)
            if outer is None:
                continue
            coords = [
                (float(c.split(',')[0]), float(c.split(',')[1]))
                for c in outer.text.strip().split()
            ]
            if len(coords) >= 3:
                polys.append(Polygon(coords))
    return MultiPolygon(polys)


def count_kml_placemarks(path):
    return len(etree.parse(path).findall('.//k:Placemark', NS))


def load_planilha_geotecnica(base_dir):
    """
    Lê PLANILHA_COMPLETA_VERIFICADA.xlsx, aba 'COM COORDENADAS'.
    Cabeçalho real está na linha 2 (índice 1); linhas 3-4 são subcabeçalhos
    de granulometria (Nº10/Nº40/Nº200) e são descartadas dos dados.
    """
    f = os.path.join(base_dir, "01_Bases_Tabulares", "PLANILHA_COMPLETA_VERIFICADA.xlsx")
    df = pd.read_excel(f, sheet_name="COM COORDENADAS", header=1)
    df = df.drop(index=[0, 1]).reset_index(drop=True)

    rename = {
        'FONTE': 'fonte', 'OBRA': 'obra', 'ORDEM': 'ordem', 'PROVÍNCIA': 'provincia',
        'IDENTIFICAÇÃO Nº': 'identificacao', 'COORDENADAS': 'zona_utm',
        'Unnamed: 7': 'utm_e', 'Unnamed: 8': 'utm_n',
        'PROFUNDIDADE (cm)': 'prof_de', 'Unnamed: 10': 'prof_ate',
        'GRANULOMETRIA POR PENEIRAMENTO % PASSANDO': 'pass_10',
        'Unnamed: 12': 'pass_40', 'Unnamed: 13': 'pass_200',
        'L. L.': 'll', 'I. P.': 'ip', 'I. G.': 'ig',
        'CLASSIFICAÇÃO H.R.B. - AASHTO': 'aashto',
        'CLASSIFICAÇÃO TÁTIL-VISUAL': 'classif_tatil', 'COLORAÇÃO (COR)': 'cor',
        'CLASSIFICAÇÃO UNIFICADA - SUCS': 'sucs',
        'C.B.R (%)\n100%': 'cbr', 'EXPANSÃO (%)\n100%': 'expansao',
        'EDOMÉTRCO': 'edometrico', 'CORTE DIRETO': 'corte_direto',
        'POTENCIAL DE COLPASIBILIDADE': 'colapsividade',
        'Comportamento geral como subleito': 'subleito',
    }
    df = df.rename(columns=rename)
    df = df[[c for c in rename.values() if c in df.columns]]

    def conv(row):
        try:
            lon, lat = UTM33S_TO_WGS84.transform(float(row['utm_e']), float(row['utm_n']))
            return pd.Series({'lat': lat, 'lon': lon})
        except Exception:
            return pd.Series({'lat': None, 'lon': None})

    df = pd.concat([df, df.apply(conv, axis=1)], axis=1)
    return df


def load_provincias(base_dir):
    sf = shapefile.Reader(os.path.join(base_dir, "03_Limites_Administrativos", "Provincias_Angola.shp"))
    feats = []
    for sr in sf.shapeRecords():
        geom = shape(sr.shape.__geo_interface__)
        feats.append((sr.record['Nome_Prov'], geom))
    return feats


def compute_kpis(base_dir):
    df_all = load_planilha_geotecnica(base_dir)
    n_total = len(df_all)
    n_sem_coord = df_all['lat'].isna().sum()

    valid = df_all.dropna(subset=['lat', 'lon']).copy()
    plausivel = valid[(valid.lat <= 0) & (valid.lat >= -20) & (valid.lon >= 10) & (valid.lon <= 25)]
    n_suspeita = len(valid) - len(plausivel)

    mancha_atual = parse_kml_polygons(
        os.path.join(base_dir, "07_Revisao_Mancha_100926", "01_Mancha_Atual.kml"))
    mancha_revisada = parse_kml_polygons(
        os.path.join(base_dir, "07_Revisao_Mancha_100926", "04_Mancha_Solos_Vermelhos_Revisada_Proposta.kml"))

    area_atual = transform(EQUAL_AREA_ANGOLA, mancha_atual).area / 1e6
    area_revisada = transform(EQUAL_AREA_ANGOLA, mancha_revisada).area / 1e6

    def in_mancha(row):
        return mancha_atual.contains(Point(row['lon'], row['lat']))

    plausivel = plausivel.copy()
    plausivel['dentro_mancha'] = plausivel.apply(in_mancha, axis=1)
    plausivel['is_red'] = plausivel['cor'].apply(
        lambda c: None if pd.isna(c) else 'vermelho' in str(c).lower())

    resumo_csv = pd.read_csv(
        os.path.join(base_dir, "07_Revisao_Mancha_100926", "Resumo_Revisao_Mancha.csv"))

    return {
        "N_total_registros": int(n_total),
        "N_coordenadas_validas_e_plausiveis": int(len(plausivel)),
        "N_sem_coordenada": int(n_sem_coord),
        "N_coordenadas_suspeitas": int(n_suspeita),
        "area_mancha_atual_km2_recalculada": round(area_atual, 1),
        "area_mancha_revisada_km2_recalculada": round(area_revisada, 1),
        "resumo_oficial_revisao_mancha": resumo_csv.set_index('Indicador')['Valor'].to_dict(),
        "join_espacial": {
            "dentro_mancha": int(plausivel['dentro_mancha'].sum()),
            "fora_mancha": int((~plausivel['dentro_mancha']).sum()),
            "vermelho_fora": int(((plausivel.is_red == True) & (~plausivel.dentro_mancha)).sum()),
            "nao_vermelho_dentro": int(((plausivel.is_red == False) & (plausivel.dentro_mancha)).sum()),
        },
    }


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "data", "raw", "Pacote_Dados_GeoTec_Angola_Projeto_Completo"
    )
    kpis = compute_kpis(base)
    print(json.dumps(kpis, ensure_ascii=False, indent=2))
