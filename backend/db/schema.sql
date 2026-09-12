-- ============================================================
-- GeoTec Angola — Schema PostgreSQL/PostGIS
-- Baseado na seção 99 da especificação do produto.
-- Todas as tabelas preservam origem (source_type/source_file)
-- e nenhuma coluna é preenchida com valor placeholder.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------
-- 1. RASTREABILIDADE DE ORIGEM (seção 7 da especificação)
-- ------------------------------------------------------------
CREATE TABLE data_sources (
    id              SERIAL PRIMARY KEY,
    source_key      TEXT UNIQUE NOT NULL,        -- ex: 'planilha_geotecnica_ensaio'
    source_file     TEXT NOT NULL,               -- nome do arquivo original
    source_type     TEXT NOT NULL,               -- campo|ensaio|imagem_satelite|interpretacao|
                                                  -- cartografia|controle_cartografico|
                                                  -- reclassificacao_geologo|modelo|derivado|historico
    source_author   TEXT,
    source_date     DATE,
    import_date     TIMESTAMPTZ NOT NULL DEFAULT now(),
    database_version TEXT NOT NULL DEFAULT 'v1',
    notes           TEXT
);

-- ------------------------------------------------------------
-- 2. LIMITES ADMINISTRATIVOS
-- ------------------------------------------------------------
CREATE TABLE administrative_units (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    code        TEXT,
    geom        GEOMETRY(MultiPolygon, 4326) NOT NULL,
    source_id   INTEGER REFERENCES data_sources(id)
);
CREATE INDEX idx_admin_units_geom ON administrative_units USING GIST(geom);

-- ------------------------------------------------------------
-- 3. PONTOS (registro geotécnico bruto — 1 linha por furo/amostra)
-- ------------------------------------------------------------
CREATE TABLE points (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id         TEXT,                    -- IDENTIFICAÇÃO Nº da planilha original
    obra                TEXT,
    fonte               TEXT,                    -- entidade responsável pelo levantamento
    provincia_texto     TEXT,                    -- texto bruto da planilha (não normalizado)
    administrative_unit_id INTEGER REFERENCES administrative_units(id),  -- resolvido por join espacial
    geom                GEOMETRY(Point, 4326),
    utm_zona            TEXT,
    utm_e               DOUBLE PRECISION,
    utm_n               DOUBLE PRECISION,
    coordenada_status   TEXT NOT NULL DEFAULT 'valida',  -- valida|ausente|suspeita_fora_angola
    source_id           INTEGER NOT NULL REFERENCES data_sources(id),
    import_date         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_points_geom ON points USING GIST(geom);
CREATE INDEX idx_points_source ON points(source_id);
CREATE INDEX idx_points_admin_unit ON points(administrative_unit_id);

-- ------------------------------------------------------------
-- 4. CLASSIFICAÇÕES / ENSAIOS (vínculo 1:1 com o ponto de origem)
-- ------------------------------------------------------------
CREATE TABLE classifications (
    id                  SERIAL PRIMARY KEY,
    point_id            UUID NOT NULL REFERENCES points(id) ON DELETE CASCADE,
    prof_de_cm          DOUBLE PRECISION,
    prof_ate_cm         DOUBLE PRECISION,
    pass_10             DOUBLE PRECISION,
    pass_40             DOUBLE PRECISION,
    pass_200            DOUBLE PRECISION,
    ll                  TEXT,
    ip                  TEXT,
    ig                  TEXT,
    aashto_raw          TEXT,                    -- grafia original, sem normalizar
    aashto_normalizado  TEXT,                    -- normalizado (pontuação uniforme)
    classificacao_tatil TEXT,
    cor                 TEXT,
    sucs                TEXT,
    cbr                 DOUBLE PRECISION,
    expansao_pct        DOUBLE PRECISION,
    edometrico          TEXT,
    corte_direto        TEXT,
    colapsividade       TEXT,
    subleito            TEXT,
    is_vermelho         BOOLEAN,                 -- derivado de `cor` (contém 'vermelho')
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_classifications_point ON classifications(point_id);
CREATE INDEX idx_classifications_aashto ON classifications(aashto_normalizado);
CREATE INDEX idx_classifications_sucs ON classifications(sucs);
CREATE INDEX idx_classifications_cor ON classifications(cor);

-- Histórico de reclassificação manual (seção 40) — nunca sobrescreve, só acumula
CREATE TABLE classification_history (
    id              SERIAL PRIMARY KEY,
    point_id        UUID NOT NULL REFERENCES points(id) ON DELETE CASCADE,
    campo           TEXT NOT NULL,               -- ex: 'cor', 'aashto'
    valor_anterior  TEXT,
    valor_novo      TEXT,
    autor           TEXT,
    justificativa   TEXT,
    origem          TEXT,                        -- ex: 'reclassificacao_geologo'
    data            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- 5. MANCHA DE SOLOS VERMELHOS — VERSIONADA (seções 18-19)
-- ------------------------------------------------------------
CREATE TABLE red_soil_versions (
    id              SERIAL PRIMARY KEY,
    version_label   TEXT NOT NULL,               -- V01, V02, ..., FINAL
    status          TEXT NOT NULL DEFAULT 'RASCUNHO',
                    -- RASCUNHO|EM_ANALISE|VALIDACAO_GEOLOGO|VALIDACAO_GEOTECNICA|
                    -- APROVADA|OFICIAL|ARQUIVADA
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL,
    area_km2        DOUBLE PRECISION NOT NULL,   -- calculado via ST_Area em projeção métrica
    methodology     TEXT,
    author          TEXT,
    source_id       INTEGER REFERENCES data_sources(id),
    is_current      BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_red_soil_geom ON red_soil_versions USING GIST(geom);

-- Áreas de expansão/retração propostas entre versões (seção 17)
CREATE TABLE red_soil_change_areas (
    id                  SERIAL PRIMARY KEY,
    version_from_id     INTEGER REFERENCES red_soil_versions(id),
    version_to_id       INTEGER REFERENCES red_soil_versions(id),
    tipo                TEXT NOT NULL,           -- expansao_prioritaria|retracao_prioritaria|
                                                  -- expansao_sob_revisao|interna_sob_revisao
    geom                GEOMETRY(Polygon, 4326) NOT NULL,
    area_km2            DOUBLE PRECISION,
    status              TEXT NOT NULL DEFAULT 'PROPOSTA'
);
CREATE INDEX idx_change_areas_geom ON red_soil_change_areas USING GIST(geom);

-- ------------------------------------------------------------
-- 6. USUÁRIOS / PERMISSÕES (seções 89-90) — esqueleto, sem dados reais ainda
-- ------------------------------------------------------------
CREATE TABLE roles (
    id      SERIAL PRIMARY KEY,
    name    TEXT UNIQUE NOT NULL   -- ADMINISTRADOR|GEOLOGO|GEOTECNICO|GIS|ANALISTA|CONSULTA
);
INSERT INTO roles(name) VALUES
    ('ADMINISTRADOR'),('GEOLOGO'),('GEOTECNICO'),('GIS'),('ANALISTA'),('CONSULTA');

CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    email           TEXT UNIQUE,
    password_hash   TEXT NOT NULL,
    role_id         INTEGER REFERENCES roles(id),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- 7. AUDITORIA (seção 91)
-- ------------------------------------------------------------
CREATE TABLE audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    table_name  TEXT NOT NULL,
    record_id   TEXT NOT NULL,
    action      TEXT NOT NULL,       -- INSERT|UPDATE|DELETE
    old_value   JSONB,
    new_value   JSONB,
    user_id     INTEGER REFERENCES users(id),
    justificativa TEXT,
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- 8. DOCUMENTOS (RAG) — seção 52
-- ------------------------------------------------------------
CREATE TABLE documents (
    id          SERIAL PRIMARY KEY,
    filename    TEXT NOT NULL,
    doc_type    TEXT,               -- relatorio|metodologia|norma|memoria
    indexed     BOOLEAN NOT NULL DEFAULT false,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- 9. INVESTIGAÇÕES SALVAS (seção 81) e EXECUÇÕES DE ANÁLISE (seção 88)
-- ------------------------------------------------------------
CREATE TABLE investigations (
    id              SERIAL PRIMARY KEY,
    name            TEXT,
    geom            GEOMETRY(Geometry, 4326),   -- ponto, polígono, linha ou corredor
    radius_km       DOUBLE PRECISION,
    status          TEXT NOT NULL DEFAULT 'EM_ANALISE',
    comentarios     TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_investigations_geom ON investigations USING GIST(geom);

CREATE TABLE analysis_runs (
    id              SERIAL PRIMARY KEY,
    run_type        TEXT NOT NULL,      -- ex: 'statistics', 'confusion_matrix', 'cluster'
    params          JSONB,
    result          JSONB,
    database_version TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reports (
    id              SERIAL PRIMARY KEY,
    report_type     TEXT NOT NULL,
    format          TEXT NOT NULL,      -- pdf|docx|xlsx|csv|geojson|kml
    file_path       TEXT,
    params          JSONB,
    generated_by    INTEGER REFERENCES users(id),
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- VIEW de conveniência: ponto + classificação + situação espacial
-- (usada pelos endpoints /api/points e /api/statistics)
-- ------------------------------------------------------------
CREATE VIEW v_points_full AS
SELECT
    p.id, p.external_id, p.obra, p.fonte, p.provincia_texto,
    au.name AS provincia_geom,
    ST_X(p.geom) AS lon, ST_Y(p.geom) AS lat,
    p.coordenada_status,
    c.aashto_raw, c.aashto_normalizado, c.sucs, c.cor, c.colapsividade,
    c.subleito, c.is_vermelho,
    ds.source_type, ds.source_file,
    EXISTS (
        SELECT 1 FROM red_soil_versions rsv
        WHERE rsv.is_current = true AND ST_Contains(rsv.geom, p.geom)
    ) AS dentro_mancha_vigente
FROM points p
LEFT JOIN classifications c ON c.point_id = p.id
LEFT JOIN administrative_units au ON au.id = p.administrative_unit_id
LEFT JOIN data_sources ds ON ds.id = p.source_id;
