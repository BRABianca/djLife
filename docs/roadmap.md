# djLife — Roadmap

Cada fase termina com **testes verdes + resultado validável**; nada é commitado pela IA
(commits são manuais).

## Fase 0 — Fundação ✅

Estrutura do projeto, empacotamento e CLI mínima.

- [x] `pyproject.toml` (hatchling, src layout, entrypoint `djlife`)
- [x] `.gitignore`, `djlife.toml.example`
- [x] `cli.py` com `--version`; `__main__.py`
- [x] venv + `pip install -e ".[dev]"`; pytest verde; `git init`

**Critério:** `djlife --version` responde e os testes passam.

## Fase 1 — Catálogo ✅

Núcleo de dados e configuração.

- [x] `schema.sql` v1 (9 tabelas + índices + FKs)
- [x] `db.py`: `connect`/`open_catalog` (WAL, FK, `busy_timeout`), `initialize` idempotente
- [x] `config.py`: `load_config` + dataclasses tipadas + validação de `files.strategy`

**Critério:** schema aplicado, FKs ativas, config carregada e validada.

## Fase 2 — Scanner + Tags ✅

Varredura do filesystem e leitura de metadados.

- [x] `scanner.py`: `os.scandir`, filtro por extensão, normalização de path (`\\?\`),
      hash blake2b opcional, incremental por `mtime`+`size`, marcação `is_missing`
- [x] `tags.py`: leitura de ID3/Vorbis/MP4 (mutagen) → `tags` + campos de `tracks`
- [x] `scan_runs`/`scan_errors` preenchidos a cada execução
- [x] comando `djlife scan`

**Critério:** apontar para uma pasta real e obter catálogo populado + resumo por run. ✔

## Fase 3 — Consulta e relatório ✅

- [x] `report.py`: export CSV/JSON + estatísticas (por extensão, cobertura de tags, duração)
- [x] comandos `djlife report`, `djlife stats`, `djlife search`

**Critério:** relatórios legíveis e conferíveis contra a pasta. ✔

## Fase 4 — Classificação em camadas ✅

- [x] `genres.yaml` (taxonomia versionada, IDs estáveis via `slug`, aliases, mapeamento Discogs/Beatport/MusicBrainz)
- [x] carga da árvore em `genres`; `taxonomy_version` em `meta`
- [x] `classifier.py`: L0 (tags) + L1 (regras locais) → `track_genres`
- [x] comando `djlife classify`

**Critério:** faixas classificadas com proveniência e confiança; nada sobrescrito. ✔

## Fase 5 — Plano, apply e undo ✅

- [x] `planner.py`: template de caminho + diff (dry-run)
- [x] `apply`: `hardlink`/`tag_only`/`move` + tags `DJLIFE_*` + journal
- [x] `undo` reversível pelo journal
- [x] comandos `djlife plan|apply|undo`

**Critério:** aplicar plano num subconjunto e reverter sem resíduos. ✔

## Fase 6 — Duplicatas e versões ✅

- [x] 3 níveis: hash exato → fingerprint (Chromaprint) → ISRC/MBID
- [x] classificador de versão (Original/Extended/Radio/Remix/Bootleg)
- [x] política *marcar, não deletar* + quarentena

**Critério:** duplicatas agrupadas por 3 níveis, versões rotuladas e redundantes movidos
para a quarentena de forma reversível (`undo`). ✔

## Fase 7 — Integrações DJ ✅

- [x] Rekordbox: ler `master.db` (SQLCipher, extra `pyrekordbox`) e relink de paths
- [x] Serato: ler `master.sqlite` (4.x, SQLite/WAL) e relink de paths
- [x] verificação de integridade (`djlife status`) e relink dry-run por padrão (`djlife relink`)

**Critério:** mover um arquivo no modo `move`, ver a referência quebrar em `status` e
corrigi-la com `relink --apply` (com backup verificado), voltando a 0 ausentes. ✔

## Fase 8 — Interface de uso (cyberpunk) ✅

Interface web local para explorar o catálogo e entender as funcionalidades sem decorar a CLI.

- [x] `ui/data.py`: leitura do catálogo (visão geral, biblioteca, duplicatas, versões, integrações)
- [x] `ui/server.py`: servidor HTTP da stdlib (`ThreadingHTTPServer`) + endpoints JSON `/api/*`
- [x] assets cyberpunk (`index.html`, `app.css`, `app.js`) com dark/neon, grade, scanlines e glitch
- [x] aba **manual** descrevendo pipeline L0→L4, comandos e garantias de segurança
- [x] comando `djlife ui` (`--port`, `--host`, `--no-open`)

**Critério:** `djlife ui` abre a página, mostra as métricas reais do catálogo e responde os
endpoints JSON; assets e API validados via HTTP. ✔

## Fase 9 — Análise de áudio ✅

Backend plugável de análise (`analysis/`): contrato `Analyzer` + registro em `base.py`, com
`librosa` como padrão nativo e `essentia` como extra opcional (ADR-0014).

- [x] `analysis/camelot.py`: tonalidade → notação **Camelot** e **Open Key** (testável sem áudio)
- [x] `analysis/librosa_backend.py`: BPM (`beat_track`) + tonalidade (croma + perfis de Krumhansl-Kessler)
- [x] `analysis/essentia_backend.py`: `RhythmExtractor2013`/`KeyExtractor` (extra `essentia`, Linux/WSL2/Docker)
- [x] "fast analysis" (`--fast`, primeiros 90 s) coexistindo com a análise completa via `analysis_version`
- [x] `analysis/runner.py`: `build_plan` (dry-run) + `apply_plan` (upsert em `audio_analysis`; falhas em `scan_errors`)
- [x] comando `djlife analyze` (`--backend`, `--apply`, `--fast`, `--force`, `--limit`) e config `[analysis]`
- [x] BPM/tonalidade da análise no `report`/`stats` e na UI (visão geral + biblioteca)

**Critério:** rodar `scan → classify → analyze --apply` num catálogo real, ver BPM/tonalidade
gravados em `audio_analysis` (sem falhas), `stats`/`report` refletindo a cobertura da análise e
a UI mostrando as métricas. ✔

## Fase 10 — ML (embeddings e modelos) ✅

Camada L3 plugável (`ml/`): contrato `Embedder` + registro em `base.py`, com `clap`
(CLAP via transformers, roda em CPU; extra `ml`) como primeiro backend (ADR-0015).

- [x] `schema.sql` v4: tabela `embeddings` (vetor float32 LE em BLOB) + índice por modelo
- [x] `ml/vectors.py`: `pack`/`unpack`/`l2_normalize`/`cosine` sem numpy (gravação independe do extra)
- [x] `ml/clap_backend.py`: CLAP (`laion/clap-htsat-unfused`, 512 dims) com import tardio
      (`EmbeddingUnavailable` + hint do extra); modelo só carregado no primeiro `embed()`
- [x] `ml/runner.py`: `build_plan` (dry-run sem carregar o backend) + `apply_plan`
      (upsert em `embeddings`; falhas em `scan_errors`), versionado por `model_version`
- [x] `ml/neighbors.py`: k-NN sobre embeddings → propostas de gênero em `track_genres`
      com `source = "embedding"`, confiança (A/B/C) pela concordância da vizinhança
- [x] comandos `djlife embed` (`--apply`, `--force`, `--limit`, `--model`, `--window`) e
      `djlife neighbors` (`--apply`, `--k`, `--min-similarity`) + config `[ml]`
- [x] cobertura de embeddings/propostas na UI (visão geral) e pipeline L3 marcado como `parcial`

Pendente desta fase: L4 (foundation models MERT/MuQ como re-ranker) — fica para a rodada
seguinte, sobre os mesmos vetores de `embeddings`.

**Critério:** rodar `scan → classify → embed --apply → neighbors --apply` (ou com embedder
fake, sem baixar pesos) e ver vetores em `embeddings` e propostas em `track_genres`
(`source = "embedding"`), sem sobrescrever labels L0/L1; `pytest`/`ruff`/`mypy` verdes. ✔

## Fase 11 — Empacotamento ✅

Executável **onedir** do núcleo enxuto via PyInstaller (extra `packaging`, ADR-0016).

- [x] extra `packaging` (`pyinstaller>=6.0`) em `pyproject.toml`
- [x] `packaging/djlife.spec`: entrypoint `djlife/__main__.py`, `hiddenimports` do pacote
- [x] dados embutidos (`schema.sql`, `genres.yaml`, `ui/assets`) via `datas` com destino `djlife/…`
- [x] extras pesados em `excludes` (`torch`/`transformers`/`librosa`/`essentia`/`pyacoustid`/…)

**Critério:** `pyinstaller packaging/djlife.spec` gera `dist/djlife/` (~24 MB) e o binário roda
`--version`, `scan`, `classify` e `stats` **sem o venv** (dados resolvidos via `_MEIPASS`). ✔

## Riscos abertos

- **Cues/beatgrids** ao mover arquivos → mitigado por hardlink (Fase 5) e relink (Fase 7).
- **Detecção de tonalidade** (~50 % acadêmico vs ~72 % Rekordbox) → manter tag do software
  como fonte L0 quando disponível.
- **APIs externas descontinuadas** (Spotify audio-features, AcousticBrainz) → núcleo
  offline-first; Discogs `styles` como fonte principal.
- **Exposição de caminhos locais pela interface** → servidor escuta em `127.0.0.1` por padrão,
  somente leitura e sem dependências externas (nada sai da máquina).
