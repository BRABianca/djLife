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

## Fase 7 — Integrações DJ (beta) ✅

Protótipo de leitura/relink dos bancos DJ. **Marcado como beta**: não afirmamos funcionamento
completo — o foco do produto é a organização no filesystem (Fases 5 e 13).

- [x] Rekordbox: ler `master.db` (SQLCipher, extra `pyrekordbox`) e relink de paths
- [x] Serato: ler `master.sqlite` (4.x, SQLite/WAL) e relink de paths
- [x] verificação de integridade (`djlife status`) e relink dry-run por padrão (`djlife relink`)

**Critério:** mover um arquivo no modo `move`, ver a referência quebrar em `status` e
corrigi-la com `relink --apply` (com backup verificado), voltando a 0 ausentes. ✔ (beta)

## Fase 8 — Interface de uso ✅

Interface web local para explorar o catálogo e entender as funcionalidades sem decorar a CLI.

- [x] `ui/data.py`: leitura do catálogo (visão geral, biblioteca, duplicatas, versões, integrações)
- [x] `ui/server.py`: servidor HTTP da stdlib (`ThreadingHTTPServer`) + endpoints JSON `/api/*`
- [x] assets cyberpunk (`index.html`, `app.css`, `app.js`) com dark/neon, grade, scanlines e glitch
- [x] aba **manual** descrevendo pipeline L0→L4, comandos e garantias de segurança
- [x] comando `djlife ui` (`--port`, `--host`, `--no-open`)

**Critério:** `djlife ui` abre a página, mostra as métricas reais do catálogo e responde os
endpoints JSON; assets e API validados via HTTP. ✔

> **Nota (2026-11-04, pós-Fase 14):** o visual *cyberpunk* original foi substituído pela
> identidade **Tech-Noir / luxo sombrio** (ADR-0013, nota de revisão). As decisões de fundo da
> fase — HTTP da stdlib, sem build de frontend, somente leitura — permanecem intactas.

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

Pendente desta fase: L4 (foundation models MERT/MuQ) — entregue na Fase 12 (ADR-0017),
sobre os mesmos vetores de `embeddings`.

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

## Fase 12 — L4 (foundation models) ✅

Backends musicais dedicados como embedders plugáveis do L3/L4 (ADR-0017), sem mudar schema
nem o k-NN.

- [x] `ml/mert_backend.py`: MERT-v1-95M (`m-a-p/MERT-v1-95M`, 768 dims, 24 kHz) via
      `transformers` (`trust_remote_code=True`); média das camadas ocultas no tempo
- [x] `ml/muq_backend.py`: MuQ (`OpenMuQ/MuQ-large-msd-iter`, 1024 dims, 24 kHz) via pacote
      `muq` (extra `muq`); média do tempo de `last_hidden_state`
- [x] registro por dicionário em `ml/runner.py` (`_CREATORS`/`_VERSIONS`) e `EMBEDDERS`
      ampliado para `clap`/`mert`/`muq`; `--backend` de `embed`/`neighbors` aceita os três
- [x] config `[ml]` e `djlife.toml.example` documentando os backends; UI com L4 marcado `parcial`
- [x] fix do `load_config` para tolerar BOM (`utf-8-sig`) descoberto no smoke test do executável

**Critério:** `embed --backend mert|muq` seleciona o backend e grava vetores com o
`model_version` correto (ou falha cedo com `EmbeddingUnavailable` quando o extra falta);
`pytest`/`ruff`/`mypy` verdes. ✔

## Fase 13 — Operação no filesystem ✅

Consolida o foco do produto — **organizar as pastas de música no filesystem** — com exportação
de playlists, auditoria do ambiente e integração contínua (integrações DJ ficam como beta,
ADR-0018).

- [x] `playlists.py`: playlists **M3U8** por gênero/subgênero (`--by genre|subgenre`) a partir
      do catálogo, com caminhos relativos à playlist (`planner.resolve_labels` reaproveita a
      classificação primária)
- [x] comando `djlife export` (`--out`, `--by`, `--apply`, `--preview`), dry-run por padrão
- [x] `doctor.py` + `djlife doctor`: auditoria **somente leitura** (schema/PRAGMAs/`quick_check`
      do SQLite, raízes, `files.target`, extras opcionais e binários externos)
- [x] `.github/workflows/ci.yml`: matriz Python 3.11/3.12 × Linux/Windows com `ruff check`,
      `ruff format --check`, `mypy` e `pytest`

**Critério:** `djlife export --apply` grava playlists `.m3u8` conferíveis contra a pasta e o
tocador; `djlife doctor` diagnostica o ambiente sem escrever nada; CI verde nos quatro jobs. ✔

## Fase 14 — Curadoria humana ✅

Nem sempre as fontes concordam: as tags (L0), as regras (L1) e os embeddings (L3) podem apontar
para gêneros diferentes, e a decisão não é automatizável sem risco. Esta fase **separa as faixas
com conflito entre fontes** e delega ao usuário a leitura manual da faixa para definir
gênero/subgênero (ADR-0019).

- [x] `curation.py`: reúne as classificações de `track_genres` e aponta os **conflitos entre
      fontes** (`divergente` = raízes distintas; `ambígua` = mesma raiz, subgêneros distintos),
      ordenando os mais graves primeiro
- [x] comando `djlife review` (`--list`, `--limit`, `--open`, `--config`): fila interativa que
      mostra os sinais por fonte + sugestão, permite **abrir a faixa no player** (`--open`),
      pular, manter ou sair e gravar a decisão
- [x] decisão manual gravada em `track_genres` com `source = 'manual'` (confiança `A`), que passa
      a ser a **classificação primária** (`planner.SOURCE_ORDER` prioriza `manual`)
- [x] `planner`: `SOURCE_ORDER` + `_primary` priorizando `manual`; helpers públicos
      (`genre_index`, `root_and_leaf`) reaproveitados pela curadoria
- [x] `tests/test_curation.py`: conflito entre fontes, ordem (divergente antes de ambígua),
      exclusão de faixas já decididas, idempotência e precedência da decisão manual

**Critério:** `djlife review --list` lista as faixas com conflito (por fonte e nível); `djlife
review` grava a escolha do usuário como `source = 'manual'` e ela passa a valer em
`plan`/`export`/`report`; `pytest`/`ruff`/`mypy` verdes. ✔

## Fase 15 — Premium e licenciamento offline ✅

Camada paga (planos **mensal**/**vitalício**) liberada por venda **interpessoal**, com licença
local assinada e verificação **offline** (ADR-0020). A chave privada fica fora do produto; o app
embute apenas a chave pública.

- [x] `premium.py`: catálogo de planos e recursos (yt-dlp, curadoria assistida, crates) +
      `require_feature` como **gate** (licença válida *e* recurso presente em `features`)
- [x] `license.py`: assinatura **Ed25519**, claims canônicos, `machine_hash()`, expiração e
      `LicenseStatus`/`status_payload`
- [x] comandos `djlife license machine-id | generate-keypair | issue | status`
- [x] `importer.py` + comando `djlife import` (`yt-dlp`, import tardio): **primeiro recurso
      premium de fato** — consome `require_feature` (`premium.ytdlp_import`) e separa os vídeos
      baixados por item (falhas não interrompem o lote); dry-run por padrão
- [x] extra `premium` (`yt-dlp`) em `pyproject.toml` e `cryptography` no núcleo
- [x] config `[license]` (`public_key`, `license_file`) + auditoria no `doctor` e estado na UI
      (aba *premium*)
- [x] `tests/test_license.py`/`tests/test_import.py` + testes de CLI/UI cobrindo emissão,
      expiração, machine binding, gate de recurso e o bloqueio do `import` sem licença
- [x] rebranding visual para **Tech-Noir / luxo sombrio** (ADR-0013, nota de revisão)

**Critério:** `djlife license issue` gera uma licença que `djlife license status` valida offline;
licença expirada/assinada por outra chave/vinculada a outra máquina é rejeitada; `djlife import`
é **bloqueado** sem licença válida e, com licença, faz dry-run dos metadados e baixa com `--apply`;
`pytest` (234 passed)/`ruff`/`mypy` verdes. ✔

## Fase 16 — Edição ADM/owner (aba de controle de usuários) ✅

A dona precisa **gerenciar as licenças emitidas** (emitir, renovar, revogar) sem terminal e
operar em **modo owner** com tudo liberado. Esta fase adiciona a **aba admin** ao `djlife ui`
com escrita **isolada** em `/api/admin/*`, gated por token e bind local (ADR-0021, emenda à UI
somente leitura da ADR-0013).

- [x] `admin.py`: núcleo de administração — `is_enabled`/`require_token`
      (`hmac.compare_digest`), `status_public`/`status_detail`, `resolve_features`,
      `default_license_output`, `licenses_payload`, `issue`/`renew`/`revoke`/`activate_owner`
- [x] `registry.py`: registro **JSON local** independente do catálogo (`REGISTRY_SCHEMA = 1`) com
      `LicenseRecord`, `effective_status` (`active`/`expired`/`revoked`) e `add/revoke/renew`
- [x] `license.py`: `OWNER_PLAN` + `WILDCARD_FEATURE` (`*`), `feature_granted`, `parse_expiration`
      e `generate_keypair`/`load_private_key` com **passphrase** (PKCS#8 `BestAvailableEncryption`)
- [x] `premium.py`: `owner_features()`/`is_owner()` e gate ciente do curinga (dona sem trava)
- [x] config `[license]` (`private_key`, `registry_file`, `admin_token`) + defaults
- [x] comandos `djlife license owner | list | renew | revoke`, `generate-keypair --encrypt` e
      `issue` reaproveitando `admin.py` (com `--private-key-password`)
- [x] `ui/server.py`: `POST /api/admin/{issue,renew,revoke}` e `GET /api/admin/{status,licenses}`
      com gate por token (`X-Admin-Token`); catálogo segue **somente leitura**
- [x] aba **admin** na UI (`index.html`/`app.js`/`app.css`): banner de aviso, resumo do estado,
      formulário de emissão e tabela de licenças (renovar/revogar); token em `sessionStorage`
- [x] `tests/test_admin.py` + casos em `test_license.py` (owner/curinga, passphrase, expiração) e
      autorização dos endpoints admin

**Critério:** `djlife license owner` instala uma licença `owner` que libera **todos** os recursos;
`license list/renew/revoke` operam o registro JSON; a aba admin emite/renova/revoga **somente**
com token válido e recusa sem ele; o catálogo musical permanece intocado; `pytest`
(251 passed)/`ruff`/`mypy` verdes. ✔

## Fase 17 — Aprendizado a partir das correções (camada `learned`) ✅

> Spec: **ADR-0022**. Escopo aprovado: **k-NN sobre as correções** (sem treino de modelo).

A resolução de gênero deve **aprender com as correções** do usuário, sem depender de dados
externos (que são instáveis): cada decisão manual do `djlife review` realimenta uma camada
`learned` por k-NN sobre os embeddings, inserida logo acima do `embedding` —
`manual < tags < rules < learned < embedding`.

- [x] `schema.sql`: tabela `feedback` (`proposed_genre_id`, `corrected_genre_id`, `source`,
      `confidence`, `score`, `model`, `model_version`, `operator`, `created_at`) + migração
      **v4 → v5** (`db.migrate`, `SCHEMA_VERSION = 5`)
- [x] `curation.record_decision`: além do `source='manual'`, gravar o par
      **proposta × correção** em `feedback`
- [x] novo módulo `learning.py`: índice k-NN sobre embeddings de faixas com rótulo `manual`,
      voto ponderado (similaridade × recência) com limiar; grava `source='learned'` em
      `track_genres` com `score`/`model_version`
- [x] `planner.SOURCE_ORDER`: inserir `"learned": 3` (aditivo) e promover `"embedding": 4`
- [x] comando `djlife learn` (recomputa `learned`) + explicação dos vizinhos votantes no
      `djlife review`/`status`
- [x] `tests/test_learning.py`: k-NN vota com as correções; *cold start* não gera `learned`;
      `learned` perde para `manual`/`rules` e vence `embedding`; migração v4 → v5

**Critério:** após corrigir faixas via `review`, `djlife learn` grava `learned` nas faixas com
vizinhos rotulados; a ordem vira `manual < tags < rules < learned < embedding`; sem correções o
comportamento é **idêntico** ao atual; `pytest` (263 passed)/`ruff`/`mypy` verdes. ✔

## Fase 18 — Biblioteca estilo Rekordbox e onboarding da pasta raiz ✅

> Specs: **ADR-0023** (onboarding). Redesign da biblioteca alinhado a ADR-0013/ADR-0021.

Duas frentes de interface: (a) a aba **biblioteca** no estilo Rekordbox (shell de 3 colunas com
toolbar de busca, sidebar de coleção e tabela densa ordenável); (b) **primeiro acesso** guiado —
o usuário escolhe a pasta raiz pelo próprio app e, em seguida, pode escanear.

- [x] `index.html`/`app.css`/`app.js`: biblioteca com toolbar de busca, sidebar de gêneros
      (inclui "sem gênero"), tabela ordenável (título/artista/álbum/gênero/BPM/tom/formato/
      duração), painel de detalhe e barra de status; filtragem e ordenação **client-side** (L1)
- [x] `config.update_library_roots`: grava `library.roots` no TOML preservando o restante do
      arquivo (edição cirúrgica da linha `roots`)
- [x] novo módulo `ui/setup.py`: `places`/`state`/`list_directory`/`save_root` e `ScanJob`/`start_scan`
      (varredura em thread com snapshot de progresso)
- [x] `ui/server.py`: `_Server` com `cfg`/`config_path` mutáveis; rotas `GET /api/setup/status`,
      `GET /api/setup/list`, `GET /api/setup/scan`, `POST /api/setup/root`, `POST /api/setup/scan`;
      bloqueio de **mesma origem** (CSRF)
- [x] `cli.py`: o comando `ui` propaga `--config` como `config_path` para `serve`
- [x] tela de boas-vindas (`index.html`/`app.js`/`app.css`): navegador de pastas + "usar esta
      pasta" + painel de varredura com status; aparece **só** quando não há raiz configurada
- [x] `tests/test_setup.py`: edição do TOML, listagem/salvamento da raiz e fluxo HTTP de setup
      (status → list → root → scan)

**Critério:** sem `library.roots`, o `djlife ui` abre o onboarding; escolher a pasta grava o
`djlife.toml` sem perder o restante do arquivo; "escanear agora" indexa a biblioteca com status
ao vivo; com raiz já configurada o app abre direto na visão geral; `ruff`/`mypy`/`pytest`
(271 passed) verdes. ✔

## Fase 19 — Menu de organização auditável na UI (MVP) ✅

> Spec: **ADR-0024** (emenda à ADR-0013). Fecha o *core* do produto na interface: o núcleo de
> organização (Fases 4/5/13) deixa de exigir terminal e passa a rodar pela web, com revisão
> **item a item** antes de qualquer escrita no filesystem.

- [x] `ui/organize.py`: encadeia o núcleo em `TaskJob` (thread daemon + snapshot) —
      `status`, `plan_payload`, `start_classify`, `start_apply`, `start_undo`, `history`
- [x] `ui/server.py`: terceira família de escrita isolada em `/api/organize/*`
      (`scan`/`classify`/`apply`/`undo` + leitura `status`/`plan`/`history`/`job`), gated por
      token de administração (`X-Admin-Token`), mesma origem (CSRF) e bind em `127.0.0.1`
- [x] `config.update_files_settings` + rota `POST /api/setup/files`: define **destino** e
      **estratégia** (`hardlink`/`move`/`tag_only`) pela UI, preservando o restante do TOML
- [x] aba **organizar** (`index.html`/`app.css`/`app.js`): passos indexar → revisar → aplicar,
      painel de destino/estratégia, plano auditável com checkboxes (só `ready`), console de
      tarefa e histórico de lotes com **desfazer**
- [x] `tests/test_organize.py`/`tests/test_setup.py`: fluxo unitário e HTTP, exigência de token,
      round-trip `apply` → `history` → `undo` com hardlink real, gravação de `[files]`
- [x] `docs/decisoes.md`: ADR-0024

**Critério:** pela web (modo owner/admin) — varrer → classificar → gerar plano → auditar por item
→ aplicar selecionados → ver o lote no histórico → desfazer; destino/estratégia configuráveis sem
tocar em terminal; `ruff`/`mypy`/`pytest` (287 passed) verdes. ✔

## Riscos abertos

- **Cues/beatgrids** ao mover arquivos → mitigado por hardlink (Fase 5) e relink (Fase 7).
- **Detecção de tonalidade** (~50 % acadêmico vs ~72 % Rekordbox) → manter tag do software
  como fonte L0 quando disponível.
- **APIs externas descontinuadas** (Spotify audio-features, AcousticBrainz) → núcleo
  offline-first; Discogs `styles` como fonte principal.
- **Exposição de caminhos locais pela interface** → servidor escuta em `127.0.0.1` por padrão,
  sem dependências externas (nada sai da máquina). As escritas vindas da UI ficam isoladas em
  `/api/setup/*` (ADR-0023, configuração), `/api/organize/*` (ADR-0024, filesystem + journal) e
  `/api/admin/*` (ADR-0021, registro de licenças), todas gated por token/CSRF quando aplicável.
