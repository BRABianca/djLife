# djLife — Registro de Decisões (ADR)

Formato: contexto → decisão → consequências.

---

## ADR-0001 — Licença: ferramenta pessoal

**Status:** aceita (2026-10-28)

**Contexto**
Parte do ecossistema útil é incompatível com produto comercial: Essentia é **AGPL-3.0** e a
maioria dos modelos de classificação de gênero é **CC BY-NC** (MERT, MuQ, MAEST, Discogs-EffNet).

**Decisão**
Tratar o djLife como **ferramenta pessoal**. Isso libera o uso de Essentia e dos modelos
non-commercial já na concepção.

**Consequências**
- (+) melhor análise (BPM/key) e classificação disponíveis desde já;
- (−) não pode ser vendido como está; um produto futuro exigiria um núcleo permissivo separado;
- mitigação: manter o núcleo em dependências permissivas (MIT/ISC/Apache) e isolar AGPL/NC em
  extras opcionais, para preservar a porta de saída.

---

## ADR-0002 — Estratégia de arquivos: hardlink + tags

**Status:** aceita (2026-10-28)

**Contexto**
Mover arquivos quebra bibliotecas de DJ: Serato (file-centric) e Rekordbox (database-centric)
guardam caminhos/referências, e cues/beatgrids vivem nos bancos desses softwares.

**Decisão**
Padrão = **hardlink + tags**: a árvore organizada é uma projeção do catálogo, apontando para o
mesmo conteúdo, sem tocar nos originais. `tag_only` disponível. `move` fica como modo
**avançado opt-in**, com journal e relink.

**Consequências**
- (+) risco nulo para as bibliotecas de DJ; reorganização reversível e barata;
- (−) exige filesystem com suporte a hardlink (mesmo volume) — NTFS ok, cross-volume não;
- (−) o modo `move` obriga implementar relink de Rekordbox/Serato antes de ser liberado.

---

## ADR-0003 — Softwares DJ alvo

**Status:** aceita (2026-10-28)

**Contexto**
Cada software guarda estado de formas diferentes; suportar tudo amplia muito o escopo.

**Decisão**
Alvos: **Serato**, **Rekordbox** e **filesystem genérico**. Serato = `_Serato_/database V2`
(binário) + `Subcrates/`; Rekordbox = `master.db` (SQLite).

**Consequências**
- (+) cobre o fluxo real do usuário;
- (−) adiciona um módulo de parsing binário (Serato) e leitura de SQLite externo (Rekordbox);
- o catálogo já nasce com `files.path` normalizado para suportar relink futuro.

> **Nota (2026-10-29, Fase 7):** a implementação revisou os formatos. O Serato 4.x usa
> **`master.sqlite`** (SQLite, WAL), não mais o `database V2` binário (ver ADR-0012); o
> Rekordbox 6/7 usa `master.db` **cifrado com SQLCipher4** (ver ADR-0011). Os alvos
> permanecem os mesmos.

---

## ADR-0004 — Catálogo SQLite como fonte de verdade

**Status:** aceita (2026-10-28)

**Contexto**
Alternativa seria tratar o filesystem como fonte de verdade e reescrever tags para refletir
estado. Isso dificulta reclassificação e auditoria.

**Decisão**
O catálogo SQLite é a fonte de verdade; as pastas e tags são projeções. Classificações são
N:N com `source` + `confidence` (nunca sobrescritas).

**Consequências**
- (+) reclassificar é barato; histórico e proveniência preservados;
- (−) o catálogo pode divergir do disco → mitigado por varredura incremental e `is_missing`.

---

## ADR-0005 — Stack de CLI: Typer + Rich

**Status:** aceita (2026-10-28)

**Contexto**
Precisa de CLI com boa ergonomia, cores e tabelas, e fluxo `plan → diff → apply`.

**Decisão**
**Typer** (parsing/UX) + **Rich** (saída). Confiança sinalizada como **A/B/C**; respeito a
`NO_COLOR`/`FORCE_COLOR`.

**Consequências**
- (+) código enxuto e saída legível; padrão dry-run natural;
- (−) dependências extras (ambas MIT).

---

## ADR-0006 — `src/` layout com hatchling

**Status:** aceita (2026-10-28)

**Contexto**
Evitar import acidental do pacote local em testes e simplificar empacotamento.

**Decisão**
Layout `src/djlife/`, build com **hatchling**, entrypoint `djlife = djlife.cli:app`,
ferramentas `ruff` + `mypy` + `pytest`.

**Consequências**
- (+) instalação editável limpa e imports corretos nos testes;
- (−) exige `pip install -e .` para rodar o CLI fora do venv ativo.

---

## ADR-0007 — Taxonomia em YAML (`pyyaml`)

**Status:** aceita (2026-10-28)

**Contexto**
A taxonomia precisa ser legível/editável à mão, versionada e com estrutura aninhada
(gênero → subgênero), aliases e mapeamentos externos. O núcleo já usa `tomllib` (stdlib) para
a config, mas TOML é ruim para listas aninhadas profundas.

**Decisão**
Taxonomia em **YAML** (`genres.yaml` padrão embutido no pacote; `genres.local.yaml` para regras
do usuário), lida com **`pyyaml`** (MIT). Os `slug` são os IDs estáveis; `taxonomy_version` é
gravado em `meta` a cada `sync`.

**Consequências**
- (+) arquivo editável, hierárquico e diff-friendly; `pyyaml` é MIT e multiplataforma;
- (−) uma dependência a mais no núcleo (stubs `types-pyyaml` no extra `dev`);
- resolução de alias é *mais específico vence* (nó filho sobrepõe o pai em tokens iguais).

---

## ADR-0008 — Journal reversível para `apply`/`undo` (schema v2)

**Status:** aceita (2026-10-28)

**Contexto**
`apply` altera o filesystem (cria hardlinks, move arquivos, grava tags). Para cumprir o
critério "reverter sem resíduos" — e para tornar o modo `move` recuperável — é preciso registrar
cada operação com informação suficiente para desfazê-la.

**Decisão**
Adicionar a tabela **`journal`** (schema v2): cada operação (`hardlink`, `move`, `tag`) é gravada
com `batch`, `op`, `strategy`, `src`, `dst`, `file_id` e `undone`. `apply` gera um `batch` novo
(uuid curto); `undo` reverte o último batch (ou um `--batch` dado) em **ordem inversa**:
hardlink → remove destino; move → restaura original + `UPDATE files.path`; tag → remove as chaves
`DJLIFE_*`. Pastas esvaziadas são podadas até a raiz de destino (nunca ela própria).

**Consequências**
- (+) toda operação é reversível e auditável; `move` pode ser liberado com segurança;
- (+) idempotência: reinspecionar o mesmo plano gera `status = existe` (nada a fazer);
- (−) mais uma tabela e a disciplina de marcar `undone = 1` ao final de cada linha;
- (−) hardlink cross-volume falha (mesmo volume exigido, herdado do ADR-0002).

---

## ADR-0009 — Duplicatas em 3 níveis e rotulagem de versão (schema v3)

**Status:** aceita (2026-10-28)

**Contexto**
A mesma faixa costuma existir em vários formatos/qualidades (WAV, FLAC, MP3 320, rip do
rip) e o DJ precisa identificar redundâncias sem perder a melhor cópia. Comparar só por
nome/caminho não distingue duplicata real de remix/versão diferente; comparar só por hash
não detecta o mesmo áudio recodificado.

**Decisão**
Detectar duplicatas em **3 níveis**, com precisão crescente e custo crescente:
1. **hash exato** (coluna `files.hash`) — byte a byte;
2. **fingerprint** acústico (Chromaprint via `pyacoustid` + `fpcalc`, extra opcional) —
   mesmo áudio recodificado; requer `--fingerprint` (senão não é calculado);
3. **ISRC / MBID** lidos das tags (`TSRC`, `UFID:`, chaves Vorbis/MP4) — mesma gravação
   entre masters diferentes.
Cada nível gera `dup_groups` (`kind` = `hash`/`fingerprint`/`isrc`/`mbid`) e `dup_members`,
com um **keeper** por grupo escolhido por *qualidade da extensão → maior duração → maior
tamanho*. Em paralelo, `versions.py` rotula a versão da faixa
(Original/Extended/Radio/Remix/Bootleg/…) por regras de texto em `file_versions`.

**Consequências**
- (+) cobre do caso trivial (bytes iguais) ao difícil (mesma gravação, master diferente);
- (+) fingerprint é opt-in — sem `fpcalc`/`pyacoustid` o núcleo continua funcionando;
- (+) reprocessar é idempotente: `find_duplicates` limpa e reescreve os grupos;
- (−) fingerprint exige dependência externa (`fpcalc`); falhas vão para `scan_errors`.

---

## ADR-0010 — Quarentena: marcar, não deletar (reuso do journal)

**Status:** aceita (2026-10-28)

**Contexto**
Remover duplicatas de forma destrutiva é irreversível e arriscado — softwares de DJ
(Rekordbox/Serato) podem referenciar justamente a cópia "redundante". É preciso um
mecanismo de limpeza que preserve tudo e seja reversível.

**Decisão**
Política **marcar, não deletar**: `djlife dedupe` move os **não-keepers** para o
`quarantine_dir` (`[files].quarantine_dir`), organizados por `kind` de duplicata, mantendo
o keeper no lugar. Nada é apagado. A operação **reutiliza o `journal`** (ADR-0008) com
`op='move'` e `strategy='quarantine'`, então o `undo` restaura os arquivos e poda a árvore
de quarentena vazia (preservando a raiz). Como todo `apply`, o `dedupe` é **dry-run por
padrão**; só executa com `--apply --yes`.

**Consequências**
- (+) limpeza reversível e auditável sem novo mecanismo (reusa journal/undo);
- (+) seguro por padrão: sem `--apply`, apenas mostra o plano;
- (−) exige `quarantine_dir` configurado (o comando falha explicitamente se ausente);
- (−) mover para a quarentena é uma operação de filesystem — sujeita a cross-volume.

---

## ADR-0011 — Rekordbox 6/7 via `pyrekordbox` (extra opcional)

**Status:** aceita (2026-10-29)

**Contexto**
No Rekordbox 6/7 o `master.db` é um SQLite **cifrado com SQLCipher4**; `sqlite3` puro não
abre o arquivo. As referências de arquivo vivem em `djmdContent` (`FolderPath` com o caminho
completo e `FileNameL` com o nome normalizado). Reescrever a criptografia à mão seria
arriscado e desnecessário.

**Decisão**
Ler e escrever o Rekordbox via **`pyrekordbox`** (MIT), exposta como **extra opcional**
`rekordbox` (`pip install -e ".[rekordbox]"`). O import é tardio: sem a dependência, os
comandos degradam para uma mensagem (`IntegrationUnavailable`) em vez de quebrar o núcleo.
O relink atualiza `FolderPath` (e `FileNameL`) preservando o estilo de separador do caminho
original e confirma com `db.commit()`.

**Consequências**
- (+) nada de criptografia caseira; núcleo continua Python puro e offline-first;
- (+) o relink é idempotente por construção (só toca conteúdo com referência quebrada e alvo existente);
- (−) dependência de terceiro para o modo `move`; exige caminho do `master.db` na config
  (`[integrations].rekordbox_db`).

---

## ADR-0012 — Serato 4.x (`master.sqlite`) e relink com backup verificado

**Status:** aceita (2026-10-29)

**Contexto**
O Serato DJ Pro/Lite 4.x migrou do `database V2` binário para **`master.sqlite`** (SQLite,
WAL). As colunas da tabela `asset` variam entre versões/builds, e alguns caminhos são
armazenados de forma absoluta e outros relativa à biblioteca. Escrever em banco de terceiro
sem rede de segurança é inaceitável.

**Decisão**
Ler/relink de `master.sqlite` com `sqlite3` da stdlib:
- **detecção de colunas** em tempo de execução (`PRAGMA table_info`) para achar o campo de
  caminho/nome entre candidatos conhecidos (`portable_id`, `file_path`, `file_name`, …);
- **leitura read-only** (`mode=ro`; fallback para `PRAGMA query_only` quando o WAL impede a
  abertura somente-leitura), sem tocar no banco;
- **relink com backup**: antes de qualquer escrita, uma cópia é feita com **tamanho
  verificado** (`.djlife-<timestamp>.bak`); o update é transacional (rollback em erro) e a
  integridade é reavaliada ao final (`djlife status`).
O plano de relink é derivado do `journal` (`op='move'`), então o Serato só é ajustado para
onde o djLife de fato moveu os arquivos — a quarentena redireciona para o **keeper**.

**Consequências**
- (+) escrita em banco de terceiro sempre precedida de backup verificado e dry-run;
- (+) tolera variação de schema entre versões do Serato e caminhos absolutos/relativos;
- (−) o mapa de colunas pode precisar de ampliação para builds futuros do Serato;
- (−) o formato legado `database V2` (pré-4.0) fica fora do escopo até haver demanda.

---

## ADR-0013 — Interface web local cyberpunk (HTTP da stdlib)

**Status:** aceita (2026-10-29)

**Contexto**
O uso exige decorar uma CLI com 13 comandos para entender o estado do catálogo (cobertura,
classificação, duplicatas, integridade dos bancos DJ). Faltava uma superfície de uso que
explicasse as funcionalidades e mostrasse as métricas reais. Introduzir um framework web
(FastAPI/Flask) ou um bundler de frontend (Node/Vite) contraria o princípio de núcleo
Python puro e offline-first.

**Decisão**
Interface **web local** servida por **HTTP da stdlib** (`http.server.ThreadingHTTPServer`),
sem novas dependências:

- `ui/data.py` concentra as leituras (visão geral, biblioteca, duplicatas, versões,
  integrações) devolvendo estruturas JSON-serializáveis; a integridade DJ reusa
  `integrations.base.dj_status`, e os helpers de resolução (`serato_db_path`, `library_roots`)
  foram movidos para `integrations/base` para serem compartilhados com a CLI;
- `ui/server.py` expõe os assets embutidos e endpoints `/api/*` em **somente leitura**;
- assets estáticos (`index.html`, `app.css`, `app.js`) com visual cyberpunk (dark/neon, grade,
  scanlines, glitch), incluindo uma aba **manual** que descreve pipeline L0→L4, cada comando da
  CLI e as garantias de segurança;
- comando `djlife ui` (`--port`, `--host`, `--no-open`), escutando em `127.0.0.1` por padrão.

**Consequências**
- (+) zero dependências novas; frontend sem build, servido direto do pacote;
- (+) catálogo lido em conexões efêmeras e só leitura — nunca escreve no catálogo nem no
  filesystem; catalogo ausente degrada para erro tratado (HTTP 503);
- (+) documentação viva: o "manual" é gerado a partir do mesmo módulo que a UI usa;
- (−) a UI não substitui a CLI: operações de escrita (`apply`, `dedupe`, `relink`) continuam
  exclusivas da CLI, com seu fluxo dry-run/confirmação;
- (−) resolver o asset é feito em disco (`ui/assets`), o que exige o pacote instalado com os
  arquivos não-Python (garantido pelo wheel do hatchling).

---

## ADR-0014 — Análise de áudio com backend plugável: `librosa` + `essentia`

**Status:** aceita (2026-10-29)

**Contexto**
O L2 do pipeline precisa de BPM e tonalidade (para Camelot/Open Key). O Essentia seria a
escolha natural em qualidade, mas **não publica wheel para Windows** (o upstream aponta WSL) e
é **AGPL-3.0** — dependência que não pode entrar no núcleo. Ao mesmo tempo, o ambiente de
desenvolvimento é Windows e a análise precisa rodar *hoje*, sem container.

**Decisão**
Backend de análise **plugável**, com contrato `Analyzer` (`name`, `version`, `analyze`) e
registro em `analysis/base.py`:

- **padrão:** `librosa` + `soundfile` (extra `analysis`) — roda nativo no Windows, licença ISC;
  BPM via `beats.beat_track` (normalizado para 70–180) e tonalidade via croma CQT + perfis de
  Krumhansl-Kessler, convertidos para Camelot/Open Key em `analysis/camelot.py`;
- **opcional:** `essentia` (extra `essentia`), selecionável por `[analysis].backend` ou
  `--backend`, para Linux/WSL2/Docker;
- **import tardio** em ambos (`AnalysisUnavailable` com o hint do extra), como em
  `integrations` e `dedupe`;
- **`analysis_version`** distingue análise completa (`1`) de *fast analysis* (`fast-1`, primeiros
  `fast_seconds`), permitindo as duas coexistirem na UNIQUE `(file_id, analyzer, analysis_version)`;
- execução em duas etapas: `build_plan` (dry-run) e `apply_plan` (upsert em `audio_analysis`;
  falhas por arquivo vão para `scan_errors` e não interrompem o lote).

**Consequências**
- (+) análise funcional no Windows sem WSL/Docker e sem trazer AGPL para o núcleo;
- (+) trocar/adicionar analisador é só implementar o protocolo — `audio_analysis` já é
  multi-analisador (`analyzer` + `analysis_version`);
- (+) desempenho/precisão podem ser comparados entre backends no mesmo catálogo;
- (−) a precisão do `librosa` é menor que a do Essentia (suficiente para triagem, não para
  substituir o BPM do Rekordbox);
- (−) cada backend carrega dependências pesadas (numpy/scipy/numba); o extra `analysis` infla
  o ambiente de quem instala, e o empacotamento PyInstaller precisa dos dois como extras.

---

## ADR-0015 — Embeddings de áudio (L3) com backend plugável e k-NN (schema v4)

**Status:** aceita (2026-10-29)

**Contexto**
O L3 do pipeline precisa cobrir os casos que tags (L0) e regras (L1) não resolvem: faixas sem
metadados úteis, mas acusticamente parecidas com as já rotuladas. Modelos de gênero
supervisionados (MERT, MuQ) são **CC BY-NC** e exigem treino/rotulagem; vetores genéricos
(CLAP) resolvem por **similaridade**, reusando os rótulos que o catálogo já tem. Rodar
inferência pesada no Windows e guardá-la no SQLite sem inflar as dependências do núcleo
(o extra CLAP é `torch` + `transformers`, ~2 GB) é o desafio de projeto.

**Decisão**

1. **Camada plugável** `ml/`: contrato `Embedder` (`name`, `version`, `dim`, `embed`) + registro
   em `ml/base.py`; primeiro backend `clap` (`laion/clap-htsat-unfused`, 512 dims, 48 kHz),
   com **import tardio** (`EmbeddingUnavailable` + hint do extra) como em `analysis`/`dedupe`.
   O modelo é carregado só no primeiro `embed()`, então o **dry-run não baixa pesos**.
2. **Schema v4** — tabela `embeddings(file_id, model, model_version, dim, vector, created_at)`
   com PK `(file_id, model, model_version)`: múltiplos modelos/versões coexistem, e reanalisar
   com outro modelo não destrói o anterior (mesmo padrão de `audio_analysis`).
3. **Vetores como BLOB float32 little-endian** (`struct` em `ml/vectors.py`, sem `numpy`):
   gravar/ler embedding não pode depender do extra `ml`. A similaridade é **cosseno = produto
   interno** sobre vetores normalizados com `l2_normalize`.
4. **k-NN (`ml/neighbors.py`)** — referências = faixas com embedding **e** rótulo (L0/L1);
   alvos = faixas com embedding **sem** rótulo. Voto ponderado pela similaridade dos `k`
   vizinhos acima de `min_similarity`; a concordância da vizinhança vira `confidence` (A/B/C).
5. **Proveniência preservada** — a proposta é gravada em `track_genres` com
   `source = "embedding"`, **nunca** com `tags`/`rules`; a UNIQUE `(track_id, genre_id, source)`
   garante que L0/L1 não são sobrescritos nem duplicados. `neighbors` é dry-run por padrão.
6. **Execução em duas etapas**, como `analyze`: `build_plan` (dry-run) e `apply_plan`, com
   `--limit`/`--force`; falhas por arquivo vão para `scan_errors` sem interromper o lote.
7. **Config `[ml]`** (`backend`, `model`, `window_seconds`, `neighbors`, `min_similarity`) e
   comandos `djlife embed` e `djlife neighbors`. O extra é `ml` (`pip install -e ".[ml]"`).

**Consequências**
- (+) L3 funcional e *offline* para leitura: os vetores ficam no catálogo e o k-NN roda sem
  GPU, sem rede e sem o extra instalado;
- (+) trocar de modelo é só implementar `Embedder` — `embeddings` já é multi-modelo;
- (+) nenhuma label de L0/L1 é perdida: a proposta é uma linha paralela, auditável e reversível;
- (+) o núcleo continua Python puro: `vectors.py` não importa `numpy`/`torch`;
- (−) gerar embeddings exige `torch` + `transformers` (extra opcional `ml`) e o download dos
  pesos na primeira execução;
- (−) o k-NN é exaustivo (O(alvos × referências)) — adequado ao catálogo pessoal, mas não
  escala para bibliotecas muito grandes sem índice vetorial;
- (−) a qualidade depende do modelo e do tamanho da vizinhança; ajustar `--k`/`--min-similarity`
  é esperado. L4 (foundation models MERT/MuQ como re-ranker) fica para a rodada seguinte.

