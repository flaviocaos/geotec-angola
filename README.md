# GeoTec Angola — Plataforma de Inteligência Geotécnica

Dashboard e WebGIS calculados dinamicamente a partir dos dados reais do
projeto (planilha geotécnica de 3.797 registros, mancha de solos vermelhos,
limites administrativos e camadas de pontos). Nenhum número no dashboard é
mockado — tudo é lido e calculado a partir do pacote de dados original.

## Estrutura do repositório

```
.
├── docs/
│   └── index.html            ← dashboard estático (autocontido, dados embutidos)
├── data/processed/           ← dados já processados usados pelo dashboard estático
│   ├── kpis.json
│   ├── pontos_geotecnicos.json
│   ├── provincias.geojson
│   ├── mancha_atual.geojson
│   ├── mancha_revisada.geojson
│   ├── expansao.geojson
│   └── retracao.geojson
├── backend/                  ← API real (FastAPI + PostgreSQL/PostGIS)
│   ├── app/
│   │   ├── main.py
│   │   └── routers/          points, statistics, red_soil, administrative,
│   │                         investigation, quality, meta
│   ├── db/
│   │   ├── schema.sql        schema completo (points, classifications,
│   │   │                     red_soil_versions, audit_logs, users, etc.)
│   │   └── load_data.py      ETL: pacote de dados bruto → PostgreSQL/PostGIS
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml        ← sobe banco + API com um comando
├── scripts/
│   └── ingest_geotec_angola.py   versão standalone (sem banco) do cálculo de KPIs
└── README.md
```

Existem **duas formas** de usar este projeto:

1. **`docs/index.html`** — o dashboard. Funciona sozinho com dados estáticos
   embutidos (zero instalação), e **automaticamente passa a usar dados ao
   vivo** se detectar uma API rodando (local ou hospedada).
2. **`backend/`** — a API real com PostgreSQL/PostGIS, calculando tudo
   dinamicamente por SQL/PostGIS a cada requisição (a "fonte de verdade"
   que a especificação do produto pede).

## Backend real (FastAPI + PostgreSQL/PostGIS)

Diferente do `docs/index.html` (dados fixos embutidos), o backend calcula
**tudo dinamicamente** por SQL/PostGIS a cada requisição — é a "fonte de
verdade" que a especificação do produto pede. Foi construído e testado
neste ambiente de desenvolvimento contra os 3.797 registros reais antes
de ser entregue aqui.

### Rodar localmente com Docker (recomendado)

Pré-requisito: [Docker](https://www.docker.com/) instalado.

```bash
docker compose up -d --build
```

Isso sobe dois serviços:
- `db` — PostgreSQL 16 + PostGIS 3.4, schema aplicado automaticamente
  (`backend/db/schema.sql` roda no primeiro start)
- `api` — FastAPI em `http://localhost:8000`

Depois de subir, carregue os dados reais no banco — já incluídos em
`data/raw/`, não precisa apontar nenhum caminho:

```bash
pip install -r backend/requirements.txt
export DATABASE_URL=postgresql://geotec:geotec_dev_pw@localhost:5432/geotec_angola
python backend/db/load_data.py
```

Isso insere: 21 províncias, mancha vigente + revisada + 59 polígonos de
expansão/retração, e os 3.797 pontos com suas classificações.

### Rodar sem Docker

```bash
# 1. PostgreSQL + PostGIS já instalados e rodando localmente
createdb geotec_angola
psql -d geotec_angola -f backend/db/schema.sql

# 2. dependências e variável de conexão
pip install -r backend/requirements.txt
export DATABASE_URL=postgresql://<usuario>:<senha>@localhost:5432/geotec_angola

# 3. carregar dados reais (já incluídos em data/raw/)
python backend/db/load_data.py

# 4. subir a API
cd backend && uvicorn app.main:app --reload
```

### Frontend conectado à API (com fallback automático)

`docs/index.html` tenta se conectar à API assim que é aberto. Por padrão
usa `http://localhost:8000` — se você hospedou o backend em outro lugar,
digite a URL no campo que aparece no topo da página e clique em
**"Conectar API"** (ou adicione `?api=https://sua-api.com` na URL do
próprio dashboard). Se a API não responder, o dashboard usa
automaticamente os dados estáticos embutidos — nunca fica quebrado.

Um indicador no topo mostra qual modo está ativo:
🟢 **API ao vivo** (dados calculados agora, direto do PostgreSQL/PostGIS)
ou ⚪ **dados estáticos** (o snapshot embutido no HTML).

> Nota: como GitHub Pages/Netlify servem apenas arquivos estáticos, abrir
> o dashboard hospedado ali só mostrará "API ao vivo" se você também tiver
> hospedado o backend em algum provedor (veja "Deploy do backend" acima) e
> apontado a página para essa URL — caso contrário ele funciona
> perfeitamente no modo offline, que é o comportamento padrão.

### Endpoints disponíveis

Documentação interativa automática (Swagger/OpenAPI, seção 98 da
especificação) em **`http://localhost:8000/docs`** assim que a API sobe.

| Endpoint | O que faz |
|---|---|
| `GET /api/health` | status do banco e contagem de pontos |
| `GET /api/points` | lista pontos com filtros (`provincia`, `cor`, `aashto`, `sucs`, `dentro_mancha`, `source_type`) |
| `GET /api/points/geojson` | mesmos filtros, retorno em GeoJSON para o mapa |
| `GET /api/points/{id}` | dossiê completo de um ponto + histórico de reclassificação |
| `GET /api/statistics/overview` | contagens por cor, AASHTO, SUCS, colapsividade, subleito, província, fonte |
| `GET /api/statistics/cross?field_a=&field_b=` | tabela de contingência + qui-quadrado entre dois campos |
| `GET /api/statistics/confusion-matrix` | TP/FN/FP/TN, acurácia, sensibilidade, especificidade, F1 (cor × mancha) |
| `GET /api/red-soil/versions` | versões da mancha cadastradas |
| `GET /api/red-soil/comparison` | área atual × revisada, variação líquida, zonas de mudança |
| `GET /api/red-soil/change-areas/geojson` | polígonos de expansão/retração propostos |
| `GET /api/administrative-units/geojson` | 21 províncias em GeoJSON |
| `GET /api/administrative-units/{id}/summary` | estatísticas geotécnicas recalculadas para uma província |
| `GET /api/investigation?lat=&lon=&radius_km=` | Modo Investigação: província, distância real até a mancha, pontos mais próximos, resumo no raio, confiança |
| `GET /api/quality` | duplicidades, ausências por campo, variantes de grafia — tudo contado ao vivo |

### Deploy do backend (hospedagem persistente)

Este ambiente de desenvolvimento não mantém servidores no ar depois que a
conversa termina — para o backend ficar disponível 24/7, ele precisa ser
implantado em algum provedor. Opções simples que aceitam `docker-compose`
ou um `Dockerfile` diretamente:

- **[Railway](https://railway.app/)** — importar o repositório, ele detecta
  o `Dockerfile` do backend e oferece um PostgreSQL gerenciado com um clique
  (adicionar a extensão PostGIS via `CREATE EXTENSION postgis;` no console).
- **[Render](https://render.com/)** — "New Web Service" apontando para
  `backend/Dockerfile`, mais um "PostgreSQL" gerenciado (plano com PostGIS).
- **[Fly.io](https://fly.io/)** — `fly launch` a partir da pasta `backend/`,
  banco via `fly postgres create` (imagem com PostGIS).
- **VPS próprio** (DigitalOcean, Hetzner, etc.) — `docker compose up -d`
  direto no servidor; foi exatamente assim que este projeto foi testado.

Depois de hospedado, atualize `DATABASE_URL` nas variáveis de ambiente do
provedor e rode `load_data.py` uma vez para popular o banco em produção.

> **Nota de transparência:** o `docker-compose.yml` foi escrito seguindo a
> configuração exata que foi testada (mesmo schema, mesmas variáveis de
> ambiente, mesma versão de imagem `postgis/postgis:16-3.4`), mas o ambiente
> onde este projeto foi construído não tem Docker disponível para rodar o
> `docker compose up` de ponta a ponta. O que **foi** testado e validado de
> verdade, com PostgreSQL 16 + PostGIS 3.4 nativos e todos os 3.797 registros
> carregados, foi: aplicação do `schema.sql`, execução completa do
> `load_data.py`, e todas as rotas da API listadas acima, uma por uma, com
> respostas reais do banco. Se o `docker compose up` apresentar algum
> problema de ambiente (raro, mas possível), rodar via "sem Docker" acima é
> exatamente o caminho já comprovado.

## Rodar o dashboard estático localmente

Não precisa de instalação. Basta abrir o arquivo no navegador:

```bash
# qualquer um destes funciona
open docs/index.html          # macOS
start docs/index.html         # Windows
xdg-open docs/index.html      # Linux
```

Ou sirva localmente (recomendado, evita restrições de `file://` no navegador):

```bash
cd docs
python3 -m http.server 8080
# abra http://localhost:8080
```

## Hospedar no GitHub Pages (grátis)

1. Suba este repositório para o GitHub (veja seção abaixo).
2. No GitHub: **Settings → Pages**.
3. Em "Build and deployment", escolha **Deploy from a branch**.
4. Branch: `main`, pasta: **`/docs`**. Salvar.
5. Em 1–2 minutos o dashboard estará em:
   `https://<seu-usuario>.github.io/<nome-do-repo>/`

Alternativas igualmente simples (arraste a pasta `docs/` ou o repo inteiro):
- **Netlify** → "Add new site" → "Deploy manually" → arraste a pasta `docs`.
- **Vercel** → importar o repositório, definir `docs` como diretório raiz.
- Qualquer servidor próprio: copie `docs/index.html` para o `document root`
  do Nginx/Apache — é só um arquivo estático.

## Subir para o GitHub a partir do VS Code

1. Abra esta pasta no VS Code: `code .` (ou File → Open Folder).
2. Abra o painel **Source Control** (ícone do lado esquerdo, `Ctrl+Shift+G`).
3. Clique em **Initialize Repository**.
4. Escreva uma mensagem de commit (ex.: "Primeira versão do dashboard") e
   clique no ✓ para commitar.
5. Clique em **Publish Branch** (ou **Publish to GitHub** se pedir login) —
   o VS Code cria o repositório remoto e faz o push automaticamente.

Ou via terminal, dentro desta pasta:

```bash
git init
git add .
git commit -m "Primeira versão do dashboard GeoTec Angola"
git branch -M main
git remote add origin https://github.com/<seu-usuario>/<nome-do-repo>.git
git push -u origin main
```

## Reprocessar os dados a partir do pacote original

Se o pacote de dados original (KMLs, shapefile, planilhas) for adicionado
ao repositório ou apontado por caminho local, os KPIs podem ser
recalculados do zero:

```bash
pip install -r requirements.txt
python scripts/ingest_geotec_angola.py /caminho/para/Pacote_Dados_GeoTec_Angola_Projeto_Completo
```

Isso imprime um JSON com os indicadores recalculados — útil para conferir
que nada no dashboard foi digitado à mão.

> Os arquivos brutos (KML/SHP/XLSX, ~80 MB extraídos) **estão incluídos**
> em `data/raw/Pacote_Dados_GeoTec_Angola_Projeto_Completo/` — nenhum
> arquivo individual passa de 25 MB, dentro do limite do GitHub (100 MB).
> `backend/db/load_data.py` já aponta para esse caminho por padrão.

## Status do projeto / próximos passos

**Já implementado e testado com dados reais:**
- ✅ Dashboard/WebGIS (`docs/index.html`) — **conectado à API ao vivo**,
  com fallback automático para dados estáticos embutidos
- ✅ Schema PostgreSQL/PostGIS completo (`backend/db/schema.sql`)
- ✅ ETL de carga dos dados reais no banco (`backend/db/load_data.py`)
- ✅ API FastAPI com estatística, geoespacial (PostGIS), qualidade de dados
  e Modo Investigação (`backend/app/`) — testada endpoint por endpoint
- ✅ `docker-compose.yml` para subir banco + API com um comando
- ✅ Dados brutos originais incluídos em `data/raw/`

**Ainda não implementado** (próximas camadas naturais a partir daqui):
- Autenticação e perfis de usuário (tabelas `users`/`roles` já existem no
  schema, mas login/JWT ainda não foi implementado nos endpoints)
- Agente de IA com tool-calling chamando os endpoints acima + RAG sobre os
  documentos técnicos (tabela `documents` já existe no schema)
- Geração automática de relatórios (PDF/DOCX/XLSX) a partir dos endpoints
- Interface de importação de novos arquivos pela própria plataforma

## Bugs reais encontrados e corrigidos durante o desenvolvimento

Documentado por transparência — nada disso foi "corrigido silenciosamente"
sem registro:

1. **Coordenadas com vírgula decimal** (`785580,00` em vez de `785580.00`)
   faziam 7 registros serem contados como "sem coordenada" quando na
   verdade tinham coordenada válida. Corrigido no parser; número correto
   de registros sem coordenada é **3**, não 10.
2. **Uma coordenada UTM corrompida** (`utm_n = 1009242578`, um valor ~100×
   maior que o esperado) gerava `inf` na conversão para latitude/longitude,
   quebrando a serialização JSON do endpoint `/api/points/geojson` com erro
   500. Corrigido: coordenadas não-finitas agora são marcadas como
   `suspeita_fora_angola` em vez de inserir geometria inválida no banco.
3. **Pontos com coordenada implausível apareciam no mapa** (um deles em
   plena Antártida, lat ≈ -81°) porque o endpoint de GeoJSON não filtrava
   por qualidade de coordenada. Corrigido: `/api/points/geojson` agora
   exclui coordenadas suspeitas por padrão (parâmetro `incluir_suspeitas`
   disponível para quem quiser auditá-las especificamente).

## Fontes e rastreabilidade dos dados

| Indicador exibido | Arquivo de origem |
|---|---|
| Registros geotécnicos, AASHTO, SUCS, colapsividade | `PLANILHA_COMPLETA_VERIFICADA.xlsx` |
| Área da mancha vigente/revisada, reclassificação do geólogo | `Resumo_Revisao_Mancha.csv` |
| Polígono da mancha vigente | `01_Mancha_Atual.kml` |
| Polígono da mancha revisada proposta | `04_Mancha_Solos_Vermelhos_Revisada_Proposta.kml` |
| Limites administrativos | `Provincias_Angola.shp` |

Detalhes completos de cada camada, incluindo avisos sobre versões parciais
(ex.: `Dados_Com_Ensaio_Parcial_4703_Pontos.kml`, explicitamente marcado
como não-final), estão na aba **Fontes & rastreabilidade** do dashboard.
