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

## Fase 9 — Análise de áudio

- [ ] `essentia`: BPM (`RhythmExtractor2013`) e tonalidade → `audio_analysis`
- [ ] "fast analysis" (primeiro minuto) para triagem rápida
- [ ] notação Camelot/Open Key

## Fase 10 — ML (embeddings e modelos)

- [ ] L3: embeddings CLAP + k-NN
- [ ] L4: foundation models (MERT/MuQ) como re-ranker

## Fase 11 — Empacotamento

- [ ] PyInstaller onedir; núcleo enxuto; extras on-demand

## Riscos abertos

- **Cues/beatgrids** ao mover arquivos → mitigado por hardlink (Fase 5) e relink (Fase 7).
- **Detecção de tonalidade** (~50 % acadêmico vs ~72 % Rekordbox) → manter tag do software
  como fonte L0 quando disponível.
- **APIs externas descontinuadas** (Spotify audio-features, AcousticBrainz) → núcleo
  offline-first; Discogs `styles` como fonte principal.
- **Exposição de caminhos locais pela interface** → servidor escuta em `127.0.0.1` por padrão,
  somente leitura e sem dependências externas (nada sai da máquina).
