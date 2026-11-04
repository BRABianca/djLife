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

> **Nota (2026-11-04, pós-Fase 14):** o visual *cyberpunk* (dark/neon, grade, scanlines, glitch)
> foi substituído pela identidade **Tech-Noir / luxo sombrio** (grafite, metal, dourado
> queimado) em `ui/assets/app.css`/`index.html`, com o ícone do app derivado de
> `ui/assets/branding/logo-source-original.jpg`. As decisões de fundo desta ADR — HTTP da
> stdlib, sem build de frontend, somente leitura — permanecem intactas; mudou apenas a camada
> visual (variáveis `--cyan`/`--magenta`/`--lime` mantidas como aliases por compatibilidade).

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
  é esperado. L4 (foundation models MERT/MuQ como re-ranker) foi implementado na ADR-0017.

---

## ADR-0016 — Empacotamento onedir com PyInstaller (núcleo enxuto, extras on-demand)

**Status:** aceita (2026-10-29)

**Contexto**
O djLife precisa rodar em máquinas de DJ sem exigir Python ou o venv de desenvolvimento. Fazer
isso sem arrastar as dependências pesadas do projeto (CLAP = `torch` + `transformers`, ~2 GB;
`librosa`; `essentia`) é o ponto central: inflá-las tornaria a distribuição proibitiva e ainda
esbarraria na ausência de wheel do `essentia` no Windows (ADR-0014). Os dados embutidos
(`schema.sql`, `genres.yaml`, `ui/assets`) são lidos em runtime via `Path(__file__).with_name(...)`,
o que quebra num bundle se eles não forem embarcados junto do pacote.

**Decisão**

1. **PyInstaller onedir** via extra `packaging` (`pip install -e ".[packaging]"`) e spec versionado
   em `packaging/djlife.spec`. Roda com `pyinstaller packaging/djlife.spec` → `dist/djlife/`.
2. **Núcleo enxuto:** as dependências de runtime do `pyproject.toml` (`typer`, `rich`, `mutagen`,
   `tinytag`, `pyyaml`, `platformdirs`) são o que entra no bundle.
3. **Extras pesados em `excludes`** no spec (`torch`, `transformers`, `librosa`, `soundfile`,
   `essentia`, `numpy`/`scipy`, `pyacoustid`, `pyrekordbox`, …): os backends continuam
   **on-demand**, instalados no ambiente de quem usa. O import tardio já existente
   (`AnalysisUnavailable`/`EmbeddingUnavailable`) mantém o núcleo funcionando sem eles.
4. **Entrypoint** = `src/djlife/__main__.py` (mesmo `app()` do console script), evitando um
   script de boot duplicado.
5. **Dados embutidos** via `datas` com destino `djlife/…`, espelhando o layout do pacote — que é
   exatamente onde o `_MEIPASS` do PyInstaller posiciona os módulos congelados, mantendo
   `Path(__file__).with_name(...)` válido sem alterar o código.
6. **FFmpeg** não entra no bundle: é pré-requisito externo apenas para os backends de áudio.

**Consequências**
- (+) distribuição portátil (~24 MB, ~32 arquivos) que roda sem Python instalado;
- (+) núcleo permanece Python puro e as dependências pesadas seguem isoladas;
- (+) nenhuma mudança de código de produção: só o spec e o extra de build;
- (−) o binário **não** inclui análise/embeddings/fingerprint/Rekordbox — quem precisar dessas
  camadas usa o ambiente Python com os extras instalados;
- (−) `dist/`/`build/` não são versionados (já no `.gitignore`); o artefato é regerado localmente.

---

## ADR-0017 — Backends L4 (MERT/MuQ) como embedders plugáveis

**Status:** aceita (2026-10-30)

**Contexto**
O L4 do pipeline (foundation models musicais) previa MERT/MuQ para refinar gênero/subgênero.
Ambos são modelos **CC BY-NC** (ADR-0001) de porte médio (MERT-v1-95M ~95M; MuQ-large ~300M),
rodam em CPU e produzem vetores por *mean pooling*. Em vez de exigir um classificador
supervisionado treinado, eles entram com o mesmo contrato do L3 — a diferença é o **espaço de
embedding** (768/1024 dims) e, portanto, o `model_version` gravado no catálogo.

**Decisão**

1. **Mesmo contrato `Embedder`** (`name`, `version`, `dim`, `embed`): `mert` e `muq` são apenas
   novos registros em `ml/runner.py`, sem tocar no k-NN nem no schema (a PK
   `(file_id, model, model_version)` já suporta múltiplos modelos).
2. **`mert`** (`m-a-p/MERT-v1-95M`, 768 dims, 24 kHz) usa `Wav2Vec2FeatureExtractor` +
   `AutoModel` com `trust_remote_code=True`; import tardio do `transformers`/`torch` (extra `ml`).
   O vetor é a média das 13 camadas ocultas sobre os *time-steps* (`hidden_states`).
3. **`muq`** (`OpenMuQ/MuQ-large-msd-iter`, 1024 dims, 24 kHz) usa o pacote `muq`
   (`from muq import MuQ`); extra dedicado `muq` (`pip install -e ".[muq]"`). O vetor é a média
   do tempo de `last_hidden_state`.
4. **Áudio lido com `librosa` em 24 kHz mono** (mesma estratégia do CLAP, com fallback
   `extended()` para paths longos do Windows), alimentando o *processor*/tensor de cada modelo.
5. **`model_version` = `<model_id>@1`**; trocar de modelo cria uma linha nova em `embeddings` e
   reanalisar com `--force` não destrói os vetores de outro backend.

**Consequências**
- (+) L4 plugável reaproveitando 100% da infraestrutura de L3 (`embed`/`neighbors`/UI);
- (+) pesos NC isolados em extras opcionais, coerente com a porta de saída da ADR-0001;
- (+) nenhuma mudança de schema: multi-modelo já era suportado;
- (−) MuQ arrasta o pacote `muq` e os pesos `OpenMuQ` (CC-BY-NC 4.0, uso não comercial);
- (−) inferência de mais de um modelo sobre o mesmo catálogo custa tempo de CPU — o `--limit`
  do `embed` existe justamente para processar em lote.

---

## ADR-0018 — Integrações DJ em beta; foco no filesystem

**Status:** aceita (2026-10-30)

**Contexto**
As integrações Rekordbox (ADR-0011) e Serato (ADR-0012) foram implementadas a partir de
documentação e engenharia reversa, sem validação contra bancos reais em todos os cenários
(versões, variantes de schema, cadeados de senha). Anunciá-las como funcionalidade estável
criaria expectativa de suporte que não pode ser honrada. Ao mesmo tempo, o valor central do
djLife é a **organização do filesystem**, que é auto-contida e verificável.

**Decisão**

1. **Rekordbox e Serato passam a ser rotulados `beta`** na CLI (`--help` e aviso em execução),
   na UI (aba *integrações*) e na documentação. Não afirmamos funcionamento completo.
2. **O foco de evolução é a organização no filesystem** (`plan` → `apply` → `undo`), com
   ferramentas de apoio: `djlife export` (playlists M3U8 por gênero/subgênero) e `djlife doctor`
   (auditoria do ambiente e da organização do catálogo).
3. **Nada dos módulos de integração é removido**: `status`/`relink` continuam disponíveis e
   cobertos por testes, apenas reclassificados como experimentais.
4. **Garantias de segurança permanecem**: `relink` segue exigindo backup verificado e dry-run
   por padrão, independentemente do status beta.

**Consequências**
- (+) expectativa alinhada: o usuário sabe que integrações podem falhar e que o caminho estável é
  o filesystem;
- (+) esforço concentrado onde o retorno é verificável (plan/apply/export/doctor);
- (−) quem depende de relink automático não tem garantia de suporte — mitigado por `doctor`, que
  diagnostica o ambiente (extras, `ffmpeg`, WAL/FK, raízes) antes de tentar;
- (−) a promoção de beta para estável exigirá validação com bancos reais — fica como pendência
  futura, não bloqueante.

---

## ADR-0019 — Curadoria humana: decisão `manual` tem precedência

**Status:** aceita (2026-10-30)

**Contexto**
As camadas automáticas gravam gênero em `track_genres` com proveniência distinta (`tags` L0,
`rules` L1, `embedding` L3/L4). Em parte da biblioteca as fontes **discordam**: uma tag antiga
aponta para um gênero que não corresponde ao áudio, uma regra de regex acerta o artista mas
erra o estilo, ou o k-NN aproxima faixas limítrofes. Escolher automaticamente entre fontes
conflitantes erra em casos que só a **escuta humana** resolve — e, como o `apply` projeta o
filesystem a partir do gênero, um erro de classificação vira um arquivo na pasta errada.

**Decisão**

1. **Detectar e separar os conflitos.** A fonte de conflito é a **divergência entre fontes**
   (não entre rótulos de uma mesma fonte). O nível é `divergente` quando as raízes de gênero
   diferem e `ambígua` quando compartilham a raiz mas divergem no subgênero; faixas `divergente`
   vêm primeiro na fila.
2. **Revisão humana via CLI interativa** (`djlife review`), sem dependência nova (só stdlib +
   Rich). O prompt mostra os sinais por fonte + uma sugestão, permite **abrir a faixa no player
   do sistema** (`--open`), além de escolher, pular, manter o rótulo atual ou sair.
3. **A decisão do usuário vence.** A escolha é gravada em `track_genres` com
   `source = 'manual'` (confiança `A`). O `planner` passa a ordenar as fontes por
   `SOURCE_ORDER = {manual: 0, tags: 1, rules: 2, embedding: 3}`, então a decisão manual é a
   **classificação primária** em `plan`/`export`/`report` — sem apagar as demais linhas
   (auditáveis).
4. **Idempotência e não-destrutividade.** Regravar a mesma decisão é `ON CONFLICT DO NOTHING`;
   faixas já revisadas (`source = 'manual'`) saem da fila. A curadoria **não** toca o filesystem.

**Consequências**
- (+) a informação incoerente é isolada e resolvida com o julgamento que falta às fontes
  automáticas, evitando arquivos em pastas erradas;
- (+) precedência explícita e reversível: a decisão manual é uma linha a mais, distinta das
  automáticas, sem removê-las;
- (+) nada de dependência nova no núcleo (stdlib + Rich), mantendo o empacotamento enxuto;
- (−) exige trabalho humano proporcional ao volume de conflitos — mitigado pela fila ordenada
  (mais graves primeiro), pelo `--limit` e por `--list`, que permitem revisar em lotes;
- (−) `SOURCE_ORDER` passa a ser parte do contrato de classificação: novas fontes precisam se
  posicionar nele.

---

## ADR-0020 — Licenciamento offline do premium com Ed25519

**Status:** aceita (2026-11-04)

**Contexto**
O djLife **não é open source** e a camada premium (planos mensal/vitalício) é liberada por venda
**interpessoal**, sem gateway de pagamento embutido. Uma checagem ingênua de flag no bytecode é
trivialmente contornável (basta um `patch`), e a validação **não pode depender de rede** — o
produto é *offline-first* e punir o cliente legítimo sem conexão seria pior que o risco de cópia.

**Decisão**

1. **Assinatura assimétrica Ed25519** (`cryptography`): a **chave privada** nunca entra no
   binário — vive com o vendedor e é usada só na emissão manual; o app embute apenas a **chave
   pública** e verifica a assinatura **offline**.
2. **Licença = arquivo local assinado** (`license.json`): `key_id` + `claims` (`schema`,
   `customer_id`, `plan`, `issued_at`, `expires_at`, `machine_hash`, `features`, `issuer`) +
   `signature` (base64). Os claims são serializados de forma **canônica** (JSON com chaves
   ordenadas e separadores fixos) antes de assinar/verificar, de modo que **qualquer** alteração
   de campo invalida a assinatura.
3. **Machine binding por hash**: `machine_hash()` deriva um identificador estável do host
   (Windows `MachineGuid`, Linux `machine-id`, macOS `IOPlatformUUID`, com fallback
   `uuid.getnode()` + node + machine). Quando o claim traz `machine_hash`, a licença só vale
   naquele host.
4. **Expiração opcional** (`expires_at`) validada contra o relógio UTC local; vitalício = `null`.
5. **Gate de recurso** (`premium.require_feature`): exige licença **válida** *e* o código do
   recurso presente em `features`; a falha levanta `PremiumUnavailable` com o motivo, em vez de
   liberar em silêncio. O primeiro consumidor é o `djlife import` (`premium.ytdlp_import`).
6. **Comandos** `djlife license machine-id | generate-keypair | issue | status`; `djlife doctor`
   audita a presença de chave pública/licença e o veredito; a UI (aba *premium*) mostra o estado.
7. **Config `[license]`** (`public_key`, `license_file`) com defaults em `user_data_dir("djlife")`.

**Consequências**
- (+) verificação **offline** e barata; sem a chave privada no binário, não há como forjar
  licenças apenas lendo o app;
- (+) emissão é um ato manual do vendedor (`issue`), coerente com a venda interpessoal;
- (+) revogação por expiração (mensal renova com nova licença) e limitação de compartilhamento
  (machine binding);
- (+) os claims canônicos impedem troca de `plan`/`features`/`expires_at` sem quebrar a
  assinatura;
- (−) adiciona `cryptography` ao núcleo (licença Apache-2.0/BSD, permissiva);
- (−) o machine binding pode punir *upgrades* de hardware/OS — mitigável emitindo o plano
  vitalício **sem** `machine_hash`;
- (−) **não é DRM**: o bytecode Python segue extraível. A proteção real é separar o premium do
  core e cobrar por valor/suporte, não por obstáculo técnico (reforça a porta de saída da
  ADR-0001).

---

## ADR-0021 — Edição ADM/owner com aba de controle de usuários (emenda à UI somente leitura)

**Status:** aceita (2026-11-04)

**Contexto**
A ADR-0013 fixou a interface web como **somente leitura**, sem escrita no catálogo nem no
filesystem. A dona (ADM) precisa, porém, **gerenciar as licenças emitidas** (emitir, renovar e
revogar) sem voltar ao terminal, e operar o produto em **modo owner** com **todos os recursos
liberados** (sem trava premium). Isso introduz a primeira escrita vinda da UI e precisa ser
contida para não violar a garantia de segurança da interface.

**Decisão**

1. **Escrita isolada em `/api/admin/*`**: as únicas rotas de escrita são `POST
   /api/admin/issue`, `POST /api/admin/renew` e `POST /api/admin/revoke`. O catálogo musical
   continua **somente leitura** — o admin escreve apenas o **registro JSON de licenças** e
   arquivos de licença, nunca o banco de músicas nem o filesystem da biblioteca.
2. **Gate por token**: toda rota admin exige o header `X-Admin-Token` (ou `token` no body),
   comparado com `hmac.compare_digest` contra `[license].admin_token`. Sem token configurado a
   administração fica **desabilitada** (`AdminUnavailable`); `GET /api/admin/status` é público e
   expõe apenas `{enabled, owner}`, sem caminhos ou dados sensíveis (os detalhes — `registry_path`,
   chaves — só saem em `GET /api/admin/licenses`, autenticado).
3. **Bind local**: emenda explícita à ADR-0013 — o servidor segue em `127.0.0.1` por padrão; a
   escrita admin só é alcançável de dentro da máquina.
4. **Modo owner (licença própria)**: `djlife license owner` emite uma licença `plan = owner` com
   `features = ("*",)` (curinga `WILDCARD_FEATURE`); `premium.is_owner` e
   `license.feature_granted` liberam **todos** os recursos. Não há trava premium para a dona.
5. **Chave privada cifrada**: `generate-keypair`/`owner` cifram a chave privada (PKCS#8,
   `BestAvailableEncryption`) com uma passphrase solicitada por sessão (`typer.prompt`
   `hide_input`); a chave privada **nunca** entra no binário nem no repositório.
6. **Registro local JSON**: as licenças emitidas são indexadas em um JSON independente do
   catálogo (`registry.py`, `REGISTRY_SCHEMA = 1`), com `effective_status`
   (`active`/`expired`/`revoked`) derivado da expiração e do próprio registro.
7. **Comandos**: `djlife license owner | list | renew | revoke`, além de `issue` reaproveitando o
   mesmo núcleo de `admin.py` — a CLI e a aba admin operam sobre o mesmo registro.

**Consequências**
- (+) a dona gerencia licenças pela UI, sem terminal, mantendo o catálogo musical intocado;
- (+) o gate por token + bind `127.0.0.1` contém o risco da primeira escrita vinda da web;
- (+) o modo owner centraliza "acesso total" numa única licença assinada, em vez de flags no
  código;
- (+) a chave privada cifrada eleva o custo de vazamento/uso indevido na máquina da dona;
- (−) **revogação offline não é DRM**: marcar um registro como `revoked` não desliga uma licença
  já entregue ao cliente (o app só verifica a assinatura). O texto de `admin.ADMIN_NOTE` deixa
  isso explícito — a revogação vale para o **registro da dona**, não como controle remoto;
- (−) a UI deixa de ser estritamente somente leitura; qualquer nova rota de escrita precisa ser
  explicitamente justificada e submetida às mesmas salvaguardas (token, `127.0.0.1`, isolamento
  do catálogo).

---

## ADR-0022 — Aprendizado a partir das correções do usuário (camada `learned`, k-NN)

**Status:** aceita (2026-11-04)

**Contexto**
O catálogo guarda vários sinais por faixa em `track_genres` e a resolução de gênero segue
`SOURCE_ORDER = {manual:0, tags:1, rules:2, embedding:3}` (ADR-0019: a curadoria manual tem
precedência máxima). O `djlife review` **já grava** cada decisão humana como `source='manual'`,
mas isso só decide caso a caso — **não realimenta** a classificação futura. Dados públicos de
gênero são instáveis e imprecisos; a fonte mais confiável é o **próprio uso**. Falta fechar o
ciclo: transformar as correções em aprendizado.

**Decisão**

1. **Camada `learned` (L3.5)**: nova fonte `learned` na resolução, inserida **logo acima do
   `embedding`**: `manual < tags < rules < learned < embedding`. A inserção é **aditiva** — não
   altera a ordem relativa das fontes existentes; sem correções, o comportamento é idêntico ao
   atual.
2. **k-NN sobre as correções (sem treino)**: cada decisão `source='manual'` vira um **vizinho
   rotulado** no índice de embeddings (L3/L4). A classificação `learned` de uma faixa é o voto
   dos `k` vizinhos rotulados, ponderado por similaridade e recência. **Não há retreinamento** de
   modelo nem fine-tuning de foundation models (MERT/MuQ/CLAP) — descartado por custo,
   inviabilidade offline e risco de esquecimento catastrófico.
3. **Registro de feedback local (schema v5)**: nova tabela `feedback` com a correção explícita —
   `proposed_genre_id` (o que o sistema propôs), `corrected_genre_id` (o que o usuário escolheu),
   `source` da proposta, `confidence`, `score`, `model`/`model_version` do embedding, `operator`
   e `created_at`. Migração **v4 → v5** idempotente em `db.migrate`. É o "banco de ML" local —
   fonte de verdade do aprendizado.
4. **Versionamento do índice**: o resultado do k-NN é gravado em `track_genres` como
   `source='learned'` com `score` (similaridade do voto) e um `model_version` que identifica o
   índice (modelo de embedding + versão) — reproduzível e auditável, no espírito de
   `analysis_version`.
5. **Explicabilidade obrigatória**: `djlife review`/`status` devem poder mostrar **por que** uma
   faixa virou `learned` (quais vizinhos votaram), para o usuário confiar e corrigir de novo se
   preciso.
6. **Aprendizado nunca move arquivos**: a camada `learned` só produz **classificação**; qualquer
   efeito físico continua passando por `plan`/`apply` (dry-run) — invariante do projeto.
7. **Local-only, sem telemetria**: nada do feedback sai da máquina; nenhuma coleta central
   (coerente com a ADR-0013 e a postura offline-first).
8. **Limiar e recência**: os votos usam **decaimento temporal** (concept drift) e um `k`/limiar
   mínimo de confiança; sem vizinhos rotulados suficientes (*cold start*), a faixa **não** recebe
   `learned` e cai para as fontes atuais.

**Consequências**
- (+) fecha o ciclo: as correções do `review` passam a **melhorar** a classificação, sem
  retreinar nada;
- (+) custo baixo e offline: o "modelo" é o próprio índice de embeddings + os rótulos já
  existentes;
- (+) explicável e reversível — dá para mostrar os vizinhos que votaram e reprocessar;
- (+) aditivo e seguro: enquanto não houver correções, o comportamento é idêntico ao de hoje;
- (+) abre caminho para evoluções (probe linear versionado via `djlife train`, mineração de
  regras, active learning) sem comprometer o núcleo;
- (−) exige migração de schema (v4 → v5) e um novo rank na resolução (os testes de conflito
  precisam cobrir `learned`);
- (−) sujeito a *cold start*, desbalanceamento por gênero e viés idiossincrático do usuário —
  mitigado por limiar e fallback;
- (−) requer embeddings (`extras ml`/`muq`) para as faixas elegíveis; sem embeddings, a camada
  fica inativa.

---

## ADR-0023 — Onboarding: seleção da pasta raiz no primeiro acesso

**Status:** aceita (2026-11-04)

**Contexto**
A interface web nascia exigindo um `djlife.toml` já preenchido: sem `[library] roots`, o
`djlife ui` abria um catálogo vazio e o usuário precisava voltar ao terminal para editar o
arquivo. A primeira experiência precisa deixar o usuário **apontar a pasta raiz** (onde estão as
músicas atuais e futuras) direto na aplicação. Isso reabre a questão da escrita vinda da UI, que
a ADR-0013 fixou como somente leitura e a ADR-0021 já havia emendado (apenas para licenças).

**Decisão**

1. **Tela de boas-vindas só no primeiro uso**: quando não há `library.roots` configurado,
   `GET /api/setup/status` devolve `configured = false` e a UI exibe o onboarding; com raiz
   configurada, o fluxo normal (visão geral) segue sem interrupção. Não há reabertura automática.
2. **Navegador de pastas embutido (server-side)**: `GET /api/setup/list?path=...` lista os
   subdiretórios reais pelo servidor (stdlib `os.scandir`, via `scanner.extended` para caminhos
   longos no Windows), ocultando entradas `.`/`$`. No Windows os pontos de partida são as
   unidades existentes; nos demais, `/` e `~`. Sem dependências novas — funciona no `.exe`.
3. **Escrita isolada em `/api/setup/*`**: as únicas rotas novas de escrita são
   `POST /api/setup/root` (grava `library.roots`) e `POST /api/setup/scan` (dispara a varredura).
   O **catálogo musical continua somente leitura** e **nada no filesystem de músicas é movido** —
   `setup.save_root` toca apenas o `djlife.toml`. A varredura reusa `scanner.scan` +
   `tags.index_tags`, a mesma trilha da CLI.
4. **Edição cirúrgica do TOML**: `config.update_library_roots` reescreve **apenas** a linha
   `roots = [...]` do bloco `[library]` (ou o insere no bloco, ou cria o bloco), preservando
   comentários, chaves não modeladas e os demais blocos. Leitura em `utf-8-sig` para tolerar BOM.
5. **Configuração mutável em runtime**: o servidor passa a carregar a `Config` e o caminho do
   arquivo (`_Server.cfg`/`config_path`); após salvar a raiz, a config é recarregada e passa a
   valer para os endpoints seguintes, sem reiniciar o processo.
6. **Scan em segundo plano com status**: `POST /api/setup/scan` inicia uma thread (daemon) que
   varre cada raiz e indexa as tags; `GET /api/setup/scan` devolve um snapshot
   (`running`/`done`/`error` + `seen/new/updated/missing/indexed/errors`) para a UI acompanhar por
   *polling*. A interface oferece "escanear agora" após salvar a raiz.
7. **Mesmas salvaguardas da ADR-0021**: bind `127.0.0.1` e checagem de **mesma origem**
   (`_same_origin`, bloqueio CSRF via header `Origin`) nas rotas de escrita; caminhos de arquivo
   são validados (`is_dir`) antes de qualquer gravação.

**Consequências**
- (+) onboarding sem terminal: escolher a raiz e escanear pelo navegador, no espírito offline-first;
- (+) o `djlife.toml` permanece a fonte da configuração, editado de forma mínima e legível;
- (+) reuso do núcleo (`scanner`/`tags`) — a UI não reimplementa a varredura;
- (+) a garantia "nada move arquivos" é preservada: o setup só grava configuração;
- (−) a UI ganha uma segunda família de rotas de escrita; como na ADR-0021, toda nova rota precisa
  justificativa e as mesmas salvaguardas;
- (−) o status do scan vive em memória (por processo); reiniciar o servidor durante a varredura
  perde o acompanhamento (a varredura pode ser refeita a qualquer momento).


