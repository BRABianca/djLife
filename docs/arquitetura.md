# djLife — Arquitetura

## 1. Visão de componentes

```
                 ┌────────────┐
   filesystem ──▶│  scanner   │──▶ files · scan_runs · scan_errors
                 └────────────┘
                        │
                 ┌────────────┐
                 │   tags     │──▶ tags · tracks
                 └────────────┘
                        │
  genres.yaml ──▶┌────────────┐
    (taxonomia)  │ classifier │──▶ track_genres (source · confidence · score)
                 └────────────┘
                        │
                 ┌────────────┐
                 │  versions  │──▶ file_versions (Original/Extended/Radio/…)
                 └────────────┘
                        │
                 ┌────────────┐
                 │   dedupe   │──▶ dup_groups · dup_members (hash → fingerprint → ISRC/MBID)
                 └────────────┘
                        │
                 ┌────────────┐
                 │  planner   │──▶ plano + diff (dry-run)
                 └────────────┘
                        │
                 ┌────────────┐
                 │   apply    │──▶ hardlink/move · tags DJLIFE_* · journal (undo)
                 └────────────┘
                        │
                 ┌────────────┐
                 │ quarantine │──▶ move redundantes p/ _Quarentena · journal (undo)
                 └────────────┘
                        │
                 ┌────────────┐
                 │  analysis  │──▶ audio_analysis (BPM · tonalidade Camelot/Open Key)
                 └────────────┘
                        │
                 ┌────────────┐
                 │     ml     │──▶ embeddings (CLAP) · track_genres (source=embedding)
                 └────────────┘
                        │
                 ┌────────────┐
                 │  report    │──▶ CSV · JSON · estatísticas
                 └────────────┘
                        │
                 ┌────────────┐
                 │integrations│──▶ relink de paths (Rekordbox/Serato) + backup verificado
                 └────────────┘
                        │
                 ┌────────────┐
                 │     ui     │──▶ página local (só leitura) + /api/* JSON
                 └────────────┘
```

O **catálogo SQLite** é o eixo central: scanner escreve, classifier anota, planner lê, apply
projeta no filesystem e grava journal.

## 2. Pipeline de classificação (L0 → L4)

| Camada | Fonte | Custo | Confiança típica | Estado |
|---|---|---|---|---|
| **L0** | Tags embutidas (`TBPM`, `TKEY`, `TCON`) | ~0 | A | ok |
| **L1** | Regras locais + taxonomia (`genres.yaml`) | baixo | A/B | ok |
| **L2** | DSP (BPM/key/energia) + classificador | médio | B | parcial (BPM/key via `librosa`) |
| **L3** | Embeddings (CLAP) + k-NN | alto | B | parcial (CLAP + k-NN, `source=embedding`) |
| **L4** | Foundation models (MERT/MuQ) | alto | B | futuro |

Cada resultado grava `source` + `confidence` (`A`/`B`/`C`) em `track_genres`; nada é
sobrescrito — camadas se acumulam e a decisão final é explícita.

## 3. Modelo de dados (schema v4)

| Tabela | Papel | Campos-chave |
|---|---|---|
| `meta` | estado do catálogo | `schema_version`, `taxonomy_version` |
| `files` | arquivos físicos | `path` (único), `size`, `mtime`, `hash`, `is_missing` |
| `tracks` | identidade lógica da faixa (base do dedupe) | `file_id`, `title`, `artist`, `album`, `duration` |
| `tags` | tags cruas lidas do arquivo | `file_id`, `namespace`, `key`, `value` |
| `audio_analysis` | análise versionada por analisador | `analyzer`, `analysis_version`, `bpm`, `key_camelot`, `key_open`, `energy`, `loudness_lufs` |
| `genres` | árvore de gêneros | `slug` (único, ex. `house.deep_house`), `parent_id`, `level`, `is_active`, `replaced_by` |
| `track_genres` | classificação N:N | `track_id`, `genre_id`, `source`, `confidence`, `score` |
| `scan_runs` | histórico de varreduras | `root`, `status`, `files_seen/new/updated/missing`, `errors` |
| `scan_errors` | erros por varredura (inclui falhas de fingerprint) | `run_id`, `path`, `message` |
| `journal` | log reversível de `apply`/`dedupe` (base do `undo`) | `batch`, `op`, `strategy`, `src`, `dst`, `file_id`, `undone` |
| `fingerprints` | fingerprint acústico por arquivo (Chromaprint) | `file_id` (PK), `fingerprint`, `duration`, `source` |
| `dup_groups` | grupos de duplicatas detectados | `kind` (`hash`/`fingerprint`/`isrc`/`mbid`), `key` (único por kind) |
| `dup_members` | arquivos de cada grupo + keeper | `group_id`, `file_id`, `is_keeper` |
| `file_versions` | versão rotulada da faixa | `file_id` (PK), `version`, `source`, `confidence` |
| `embeddings` | vetor de áudio versionado por modelo (L3) | `file_id`, `model`, `model_version`, `dim`, `vector` (BLOB float32) |

DDL em [`src/djlife/schema.sql`](../src/djlife/schema.sql). Acesso em `db.py`
(`connect`, `open_catalog`, `initialize`).

## 4. Estratégia de arquivos

| Estratégia | O que faz | Risco | Uso |
|---|---|---|---|
| `hardlink` (default) | cria árvore organizada apontando para o mesmo conteúdo | nulo p/ DJ | padrão |
| `tag_only` | só grava tags `DJLIFE_*`, não cria pastas | nulo | bibliotecas gerenciadas por software |
| `move` (opt-in) | move o original e atualiza o catálogo | alto (quebra bibliotecas) | avançado, com relink |
| `quarantine` | move redundantes (não-keepers) p/ `_Quarentena`, mantendo o keeper | médio (reversível) | limpeza de duplicatas |

Template de caminho: `{genre}/{subgenre}/{artist} - {title}`, com `_NaoClassificado` para
o que não foi resolvido.

Política **marcar, não deletar**: nada é apagado. Os redundantes vão para o
`quarantine_dir` (config `[files].quarantine_dir`), organizados por `kind` de duplicata, e
podem ser restaurados pelo `undo`. O keeper de cada grupo (melhor qualidade de extensão →
maior duração → maior tamanho) permanece no lugar.

## 5. Fluxo de CLI

```
djlife scan       → varre raízes, atualiza `files` (incremental por mtime+size)
djlife classify   → resolve gênero em camadas (L0…), grava `track_genres`
djlife versions   → rotula versão (Original/Extended/Radio/Remix/…) em `file_versions`
djlife analyze    → BPM + tonalidade (Camelot/Open Key) → `audio_analysis` (dry-run; `--apply`)
djlife embed      → vetores de áudio (CLAP) → `embeddings` (dry-run; `--apply`)
djlife neighbors  → k-NN propõe gênero p/ faixas sem rótulo → `track_genres` (dry-run; `--apply`)
djlife duplicates → agrupa duplicatas (hash → fingerprint → ISRC/MBID) em `dup_groups`
djlife dedupe     → move redundantes p/ quarentena (dry-run por padrão; `--apply`)
djlife plan       → gera plano + diff do que seria criado/movido (dry-run)
djlife apply      → executa o plano (hardlink/move + tags + journal)
djlife undo       → reverte o último apply/dedupe pelo journal
djlife status     → integridade dos bancos DJ (itens que resolvem p/ arquivos existentes)
djlife relink     → reposiciona paths nos bancos DJ (dry-run por padrão; `--apply`)
djlife ui         → sobe a interface web local (só leitura) em `127.0.0.1`
djlife report     → exporta CSV/JSON + estatísticas
```

Convenções: Typer + Rich, barras de confiança A/B/C, respeito a `NO_COLOR`/`FORCE_COLOR`.
`dedupe` e `apply` são **dry-run** por padrão; `--apply --yes` executa de fato.

## 6. Integrações DJ

| Software | Como armazena | Arquivo | Estratégia |
|---|---|---|---|
| **Rekordbox** | database-centric | `master.db` (SQLite **cifrado**, SQLCipher4) | ler + relink via `pyrekordbox` (extra `rekordbox`) |
| **Serato** | file-centric | `master.sqlite` (SQLite, WAL) | ler + relink; colunas detectadas por `PRAGMA table_info` |
| **filesystem** | — | árvore de arquivos | padrão |

Com `hardlink`/`tag_only`, os originais não se movem e as bibliotecas continuam válidas sem
relink. Relink só é necessário no modo `move`.

Config em `[integrations]` (`rekordbox_db`, `serato_db`) e comandos:

- `djlife status` — integridade: quantos itens resolvem para arquivos existentes (amostra dos ausentes);
- `djlife relink` — deriva os ajustes do `journal` (`op='move'`; quarentena → keeper), mostra o
  plano dry-run e, com `--apply --yes`, grava **somente após backup verificado** (cópia com
  tamanho conferido) e reavalia a integridade ao final.

## 7. Interface de uso (web local)

Superfície de uso que explica as funcionalidades e mostra as métricas reais do catálogo, sem
dependências novas e sem build de frontend (ADR-0013).

| Camada | Arquivo | Papel |
|---|---|---|
| Dados | `ui/data.py` | leituras do catálogo → JSON (`overview`, `tracks`, `duplicates`, `versions`, `integrations`, `capabilities`) |
| Servidor | `ui/server.py` | `ThreadingHTTPServer` (stdlib): assets em `ui/assets` + endpoints `/api/*` |
| Assets | `ui/assets/` | `index.html`, `app.css`, `app.js` (dark/neon, grade, scanlines, glitch) |

Endpoints: `/api/overview`, `/api/tracks?q=&limit=`, `/api/duplicates`, `/api/versions`,
`/api/integrations`, `/api/capabilities`, `/api/version`.

Abas da página: **visão geral**, **biblioteca**, **duplicatas**, **versões**, **integrações** e
**manual** (pipeline L0→L4, comandos e garantias de segurança). O servidor é **somente
leitura**: abre conexões efêmeras, não escreve no catálogo nem no filesystem, escuta em
`127.0.0.1` por padrão e resolve assets bloqueando travessia de diretório.

## 8. Performance

- `os.scandir` (não `os.walk`) + prefixo `\\?\` para paths longos no Windows;
- varredura incremental por `mtime` + `size`; `scan_runs` registra o diff;
- SQLite em **WAL**, `synchronous=NORMAL`, `busy_timeout`;
- ThreadPool para I/O (hashing/leitura) e ProcessPool para CPU (DSP).

## 9. Dependências e licenças

| Camada | Pacote | Licença | Nota |
|---|---|---|---|
| CLI/UI | `typer`, `rich` | MIT | núcleo |
| Servidor da UI | `http.server` (stdlib) | PSF | núcleo; sem dependência extra |
| Tags | `mutagen` | GPL-2.0 | leitura **e escrita**; ok p/ uso pessoal |
| Tags (rápido) | `tinytag` | MIT | leitura |
| Taxonomia | `pyyaml` | MIT | leitura de `genres.yaml` / `genres.local.yaml` |
| Paths/config | `platformdirs` | MIT | núcleo |
| Fingerprint | `pyacoustid` + `fpcalc` | MIT | extra `fingerprint` |
| Rekordbox | `pyrekordbox` | MIT | extra `rekordbox`; lê/relink `master.db` (SQLCipher) |
| Análise (padrão) | `librosa` + `soundfile` | ISC | extra `analysis`; roda nativo no Windows/Linux/macOS |
| Análise (opcional) | `essentia` | AGPL-3.0 | extra `essentia`; **sem wheel Windows** (WSL2/Docker) |
| Embeddings (L3) | `torch` + `transformers` | BSD-3/Apache-2.0 | extra `ml`; CLAP (`laion/clap-htsat-unfused`), roda em CPU |
| Modelos de gênero | MERT/MuQ/MAEST | CC BY-NC | uso pessoal |

Extras opcionais: `pip install -e ".[fingerprint,rekordbox,analysis]"`; no Linux/WSL2,
`essentia` pode substituir/complementar o backend padrão (`pip install -e ".[essentia]"`).
A camada L3 exige o extra `ml` (`pip install -e ".[ml]"`); os pesos do CLAP são baixados do
HuggingFace na primeira execução (o dry-run não baixa nada).

## 10. Layout do repositório

```
djLife/
├── pyproject.toml          # hatchling, src layout, entrypoint `djlife`
├── djlife.toml.example     # config: roots, catalog, classification, files, integrations
├── genres.local.yaml.example
├── docs/                   # concepcão, arquitetura, roadmap, decisões
├── src/djlife/
│   ├── schema.sql          # DDL v4 (journal + fingerprints/dup/file_versions + embeddings)
│   ├── genres.yaml         # taxonomia padrão (versionada)
│   ├── db.py               # conexão + PRAGMAs + initialize
│   ├── config.py           # load_config (tomllib)
│   ├── scanner.py          # varredura incremental + hash
│   ├── tags.py             # leitura/escrita de tags (DJLIFE_*)
│   ├── taxonomy.py         # load_taxonomy + sync (genres/meta)
│   ├── classifier.py       # L0 tags + L1 regras → track_genres
│   ├── versions.py         # rotulagem de versão → file_versions
│   ├── dedupe.py           # 3 níveis de duplicatas → dup_groups/dup_members
│   ├── quarantine.py       # move redundantes p/ quarentena (journal + undo)
│   ├── planner.py          # template de caminho + diff (dry-run)
│   ├── apply.py            # hardlink/move/tag_only + journal + undo
│   ├── report.py           # CSV/JSON + estatísticas
│   ├── analysis/           # backends de análise: base, camelot, librosa_backend, essentia_backend, runner
│   ├── ml/                 # embeddings (L3): base, vectors, clap_backend, runner, neighbors (k-NN)
│   ├── integrations/       # Rekordbox/Serato: base, leitura + relink
│   ├── ui/                 # interface web local: data.py, server.py, assets/
│   └── cli.py              # Typer app
└── tests/
```

## 11. Empacotamento

PyInstaller **onedir**; núcleo Python puro (~10–25 MB); FFmpeg e os backends de análise
(`librosa`/`soundfile`, `essentia`) e de embeddings (`ml`: `torch`/`transformers`) como extras
on-demand para não inflar a distribuição.
