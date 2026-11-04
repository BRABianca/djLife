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
                 │  curation  │──▶ conflitos entre fontes · decisão humana (source=manual)
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
                 │  premium   │──▶ planos mensal/vitalicio · extras pagos opcionais (yt-dlp)
                 └────────────┘
                        │
                 ┌────────────┐
                 │  license   │──▶ Ed25519 · hash da maquina · expiracao · verificacao offline
                 └────────────┘
                        │
                 ┌────────────┐
                 │  registry  │──▶ registro JSON local de licencas (active/expired/revoked)
                 └────────────┘
                        │
                 ┌────────────┐
                 │   admin    │──▶ emitir/renovar/revogar · modo owner (curinga) · gate por token
                 └────────────┘
                        │
                 ┌────────────┐
                 │     ui     │──▶ página local (leitura) + /api/* JSON · escrita só em /api/admin/*
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
| **L3.5** | Correções do usuário (`feedback`) + k-NN | baixo | B | ok (`source=learned`, ADR-0022) |
| **L4** | Foundation models (MERT/MuQ) | alto | B | parcial (`mert`/`muq` como embedders, ADR-0017) |

Cada resultado grava `source` + `confidence` (`A`/`B`/`C`) em `track_genres`; nada é
sobrescrito — camadas se acumulam e a decisão final é explícita.

A **classificação primária** de uma faixa (a que `planner`/`export`/`report` usam) é escolhida
por `SOURCE_ORDER = {manual: 0, tags: 1, rules: 2, learned: 3, embedding: 4}` e depois por
confiança. Quando as fontes discordam, o conflito é isolado e resolvido por **curadoria humana**
(`djlife review`, seção 5): a decisão do usuário entra como `source = 'manual'` e passa a vencer
as automáticas, sem apagá-las (ADR-0019). As correções realimentam a camada `learned` (ADR-0022).

## 3. Modelo de dados (schema v5)

| Tabela | Papel | Campos-chave |
|---|---|---|
| `meta` | estado do catálogo | `schema_version`, `taxonomy_version` |
| `files` | arquivos físicos | `path` (único), `size`, `mtime`, `hash`, `is_missing` |
| `tracks` | identidade lógica da faixa (base do dedupe) | `file_id`, `title`, `artist`, `album`, `duration` |
| `tags` | tags cruas lidas do arquivo | `file_id`, `namespace`, `key`, `value` |
| `audio_analysis` | análise versionada por analisador | `analyzer`, `analysis_version`, `bpm`, `key_camelot`, `key_open`, `energy`, `loudness_lufs` |
| `genres` | árvore de gêneros | `slug` (único, ex. `house.deep_house`), `parent_id`, `level`, `is_active`, `replaced_by` |
| `track_genres` | classificação N:N | `track_id`, `genre_id`, `source`, `confidence`, `score`, `model_version` |
| `scan_runs` | histórico de varreduras | `root`, `status`, `files_seen/new/updated/missing`, `errors` |
| `scan_errors` | erros por varredura (inclui falhas de fingerprint) | `run_id`, `path`, `message` |
| `journal` | log reversível de `apply`/`dedupe` (base do `undo`) | `batch`, `op`, `strategy`, `src`, `dst`, `file_id`, `undone` |
| `fingerprints` | fingerprint acústico por arquivo (Chromaprint) | `file_id` (PK), `fingerprint`, `duration`, `source` |
| `dup_groups` | grupos de duplicatas detectados | `kind` (`hash`/`fingerprint`/`isrc`/`mbid`), `key` (único por kind) |
| `dup_members` | arquivos de cada grupo + keeper | `group_id`, `file_id`, `is_keeper` |
| `file_versions` | versão rotulada da faixa | `file_id` (PK), `version`, `source`, `confidence` |
| `embeddings` | vetor de áudio versionado por modelo (L3) | `file_id`, `model`, `model_version`, `dim`, `vector` (BLOB float32) |
| `feedback` | correções humanas (proposta × correção) — banco de ML local (L3.5) | `track_id`, `proposed_genre_id`, `corrected_genre_id`, `source`, `confidence`, `score`, `model`, `model_version`, `operator` |

DDL em [`src/djlife/schema.sql`](../src/djlife/schema.sql). Acesso em `db.py`
(`connect`, `open_catalog`, `migrate`, `initialize`). O `migrate` aplica os passos incrementais
(ex. v4 → v5) de forma idempotente.

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
djlife review     → revisa faixas com gênero divergente entre fontes; grava decisão `manual`
djlife analyze    → BPM + tonalidade (Camelot/Open Key) → `audio_analysis` (dry-run; `--apply`)
djlife embed      → vetores de áudio (clap/mert/muq) → `embeddings` (dry-run; `--apply`)
djlife neighbors  → k-NN propõe gênero p/ faixas sem rótulo → `track_genres` (dry-run; `--apply`)
djlife learn      → aprende com as correções do usuário (camada `learned`, k-NN) → `track_genres`
djlife duplicates → agrupa duplicatas (hash → fingerprint → ISRC/MBID) em `dup_groups`
djlife dedupe     → move redundantes p/ quarentena (dry-run por padrão; `--apply`)
djlife plan       → gera plano + diff do que seria criado/movido (dry-run)
djlife apply      → executa o plano (hardlink/move + tags + journal)
djlife undo       → reverte o último apply/dedupe pelo journal
djlife status     → integridade dos bancos DJ (itens que resolvem p/ arquivos existentes)
djlife relink     → reposiciona paths nos bancos DJ (dry-run por padrão; `--apply`)
djlife export     → playlists M3U8 por gênero/subgênero a partir do catálogo (dry-run; `--apply`)
djlife license    → gera chaves, emite/renova/revoga licenças, modo owner e valida a ativação offline
djlife import     → ingestão online via yt-dlp (premium; gate de licença; dry-run por padrão)
djlife doctor     → auditoria somente-leitura do ambiente e do catálogo
djlife ui         → sobe a interface web local em `127.0.0.1` (catálogo só leitura; admin por token)
djlife report     → exporta CSV/JSON + estatísticas
```

Convenções: Typer + Rich, barras de confiança A/B/C, respeito a `NO_COLOR`/`FORCE_COLOR`.
`dedupe` e `apply` são **dry-run** por padrão; `--apply --yes` executa de fato.

## 6. Integrações DJ (beta)

> **Beta:** a leitura e o relink dos bancos DJ não têm funcionamento garantido. O caminho
> suportado e priorizado é a organização no **filesystem** (`plan`/`apply`, seções 4 e 5).

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
| Servidor | `ui/server.py` | `ThreadingHTTPServer` (stdlib): assets em `ui/assets` + endpoints `/api/*` (leitura), `/api/setup/*` e `/api/organize/*` (escrita, gated por token) e `/api/admin/*` |
| Onboarding | `ui/setup.py` | navegação de pastas, `library.roots` no TOML, `ScanJob`/`start_scan` e `[files]` (destino/estratégia) |
| Organização | `ui/organize.py` | encadeia o núcleo (`classifier`/`planner`/`apply`) em `TaskJob` para a aba *organizar* |
| Admin | `admin.py` (via servidor) | emitir/renovar/revogar licenças no registro JSON; modo owner |
| Assets | `ui/assets/` | `index.html`, `app.css`, `app.js` (Tech-Noir / luxo sombrio) |

Endpoints de leitura: `/api/overview`, `/api/tracks?q=&limit=`, `/api/duplicates`, `/api/versions`,
`/api/integrations`, `/api/capabilities`, `/api/version`, `/api/organize/{status,plan,history,job}`.

Endpoints de administração: `GET /api/admin/status` (público: `{enabled, owner}`),
`GET /api/admin/licenses` (autenticado: detalhes + lista) e `POST /api/admin/{issue,renew,revoke}`.
Toda rota admin exige o header `X-Admin-Token` (ou `token` no body), conferido contra
`[license].admin_token` com `hmac.compare_digest`.

Abas da página: **visão geral**, **biblioteca**, **organizar** (menu auditável), **duplicatas**,
**versões**, **integrações**, **premium**, **manual** (pipeline L0→L4, comandos, oferta premium e
garantias de segurança) e **admin** (controle de licenças). As abas **admin** e **organizar**
ficam **ocultas por padrão** e só aparecem quando `[license].admin_token` está configurado — o
usuário comum vê um app limpo, sem elas.
O catálogo musical é **somente leitura** para consulta: abre conexões efêmeras e escuta em
`127.0.0.1` por padrão, resolvendo assets com bloqueio de travessia de diretório. As escritas
vindas da UI ficam **isoladas por família de rota** (todas com bloqueio de mesma origem/CSRF):
`/api/admin/*` (registro JSON de licenças, ADR-0021), `/api/setup/*` (configuração
`library.roots`/`[files]`, ADR-0023) e `/api/organize/*` (organização no filesystem + journal,
ADR-0024).

## 7.1 Licenciamento offline do premium

O premium é separado do core por uma licença local validada offline:

- a **chave privada** fica fora do produto (cifrada por passphrase) e serve apenas para emissão
  manual;
- o app carrega apenas a **chave pública** para verificar a assinatura Ed25519;
- a licença (`license.json`) inclui `customer_id`, `plan`, `issued_at`, `expires_at`,
  `machine_hash` e `features`;
- o `machine_hash` é derivado da máquina local e pode prender a licença a um único host;
- `djlife license status` e `djlife doctor` mostram se a licença está ausente, expirada,
  assinada por outra chave ou vinculada a outra máquina.

O **registro local** (`registry.py`) indexa as licenças emitidas num JSON independente do
catálogo, com estado efetivo `active`/`expired`/`revoked`. O **modo owner** (`plan = owner`,
`features = ("*",)`) libera **todos** os recursos via `premium.is_owner`/`license.feature_granted`;
a gestão (emitir/renovar/revogar) roda pela CLI (`djlife license …`) ou pela **aba admin** da UI,
ambas sobre o mesmo núcleo de `admin.py` e o mesmo registro.

## 7.2 Organização auditável pela web (aba *organizar*)

Fecha o *core* do produto na interface (ADR-0024): o fluxo `scan → classify → plan → apply →
undo` roda pela web, em **modo owner/admin**, sem sair do navegador.

- `ui/organize.py` reaproveita integralmente o núcleo (`scanner`, `taxonomy`, `classifier`,
  `planner`, `apply`) e apenas o embrulha em `TaskJob` (thread `daemon` + `snapshot()`), seguindo
  o padrão de `ui/setup.ScanJob`; a UI acompanha por *polling* em `/api/organize/job?task=`.
- **Escrita isolada** em `/api/organize/*`: `POST {scan,classify,apply,undo}` (gated por
  `X-Admin-Token` + mesma origem) e leituras `GET {status,plan,history,job}`.
- **Plano auditável**: `plan_payload` devolve itens com origem/gênero/destino/status
  (`ready`/`exists`/`conflict`/`unclassified`) e só `ready` é selecionável no frontend; o `apply`
  respeita `track_ids` (aprovação parcial) — `None` aplica todos os prontos.
- **Reversível**: cada `apply` grava um `batch` no `journal`; a aba lista os lotes e o `undo`
  reverte por lote (hardlinks removidos, moves restaurados, tags `DJLIFE_*` removidas).
- **Destino/estratégia** vêm de `[files]` (`files.target`/`files.strategy`), editáveis pela UI via
  `config.update_files_settings` + `POST /api/setup/files` (exige token), com edição cirúrgica do
  TOML que preserva comentários e demais seções.

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
| Embeddings (L3) | `torch` + `transformers` | BSD-3/Apache-2.0 | extra `ml`; CLAP (`laion/clap-htsat-unfused`) e MERT (`m-a-p/MERT-v1-95M`), rodam em CPU |
| Embeddings (L4) | `muq` | MIT (pesos CC-BY-NC) | extra `muq`; MuQ (`OpenMuQ/MuQ-large-msd-iter`), roda em CPU |
| Premium / ingestão online | `yt-dlp` | Unlicense | extra `premium`; base opcional para recursos pagos/importação |
| Modelos de gênero | MERT/MuQ/MAEST | CC BY-NC | uso pessoal |

Extras opcionais: `pip install -e ".[fingerprint,rekordbox,analysis]"`; no Linux/WSL2,
`essentia` pode substituir/complementar o backend padrão (`pip install -e ".[essentia]"`).
Os embeddings exigem o extra `ml` (`pip install -e ".[ml]"`, CLAP/MERT) — ou o extra `muq`
(`pip install -e ".[muq]"`, MuQ); os pesos são baixados do HuggingFace na primeira execução
(o dry-run não baixa nada).

## 10. Layout do repositório

```
djLife/
├── pyproject.toml          # hatchling, src layout, entrypoint `djlife`
├── djlife.toml.example     # config: roots, catalog, classification, files, integrations
├── genres.local.yaml.example
├── packaging/              # spec do PyInstaller (onedir)
├── docs/                   # concepcão, arquitetura, roadmap, decisões
├── src/djlife/
│   ├── schema.sql          # DDL v5 (journal + fingerprints/dup/file_versions + embeddings + feedback)
│   ├── genres.yaml         # taxonomia padrão (versionada)
│   ├── db.py               # conexão + PRAGMAs + initialize/migrate
│   ├── config.py           # load_config (tomllib)
│   ├── scanner.py          # varredura incremental + hash
│   ├── tags.py             # leitura/escrita de tags (DJLIFE_*)
│   ├── taxonomy.py         # load_taxonomy + sync (genres/meta)
│   ├── classifier.py       # L0 tags + L1 regras → track_genres
│   ├── curation.py         # conflitos entre fontes + decisão humana (review)
│   ├── versions.py         # rotulagem de versão → file_versions
│   ├── dedupe.py           # 3 níveis de duplicatas → dup_groups/dup_members
│   ├── quarantine.py       # move redundantes p/ quarentena (journal + undo)
│   ├── planner.py          # template de caminho + diff (dry-run)
│   ├── playlists.py        # playlists M3U8 por gênero/subgênero (export)
│   ├── apply.py            # hardlink/move/tag_only + journal + undo
│   ├── report.py           # CSV/JSON + estatísticas
│   ├── doctor.py           # auditoria somente-leitura do ambiente/catálogo
│   ├── premium.py          # planos/recursos + gate (require_feature) e modo owner
│   ├── license.py          # Ed25519: chaves, claims canônicos, machine_hash, expiração
│   ├── registry.py         # registro JSON local de licenças (active/expired/revoked)
│   ├── admin.py            # admin: emitir/renovar/revogar + gate por token (aba admin)
│   ├── importer.py         # ingestão online via yt-dlp (premium; dry-run por padrão)
│   ├── analysis/           # backends de análise: base, camelot, librosa_backend, essentia_backend, runner
│   ├── ml/                 # embeddings (L3/L4): base, vectors, clap/mert/muq_backend, runner, neighbors
│   ├── integrations/       # Rekordbox/Serato: base, leitura + relink (beta)
│   ├── ui/                 # interface web local: data.py, server.py, setup.py, organize.py, assets/
│   └── cli.py              # Typer app
└── tests/
```

## 11. Empacotamento

Distribuição **PyInstaller onedir** (extra `packaging`), núcleo Python puro — roda sem Python nem
venv (ADR-0016). Com o extra opcional `premium` instalado (yt-dlp), o bundle fica em ~42 MB;
sem ele, ~24 MB.

```
pip install -e ".[packaging]"
pyinstaller packaging/djlife.spec      # → dist/djlife/djlife.exe
```

O spec [`packaging/djlife.spec`](../packaging/djlife.spec) usa `src/djlife/__main__.py` como
entrypoint e embute os dados lidos em runtime por `Path(__file__).with_name(...)` — `schema.sql`,
`genres.yaml` e `ui/assets` — com destino `djlife/…`, que é onde o `_MEIPASS` do PyInstaller
posiciona o pacote congelado (por isso a resolução de dados não muda no código).

Os extras pesados (`analysis`, `ml`, `muq`, `essentia`, `fingerprint`, `rekordbox`) entram em
`excludes`: FFmpeg e esses backends ficam **on-demand**, instalados no ambiente Python de quem
usa. O binário cobre o núcleo (scan, tags, classificação, plano/apply, dedupe, relatório, UI,
status/relink de banco DJ).
