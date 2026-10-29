# djLife — Concepção

## 1. Objetivo

Organizar a biblioteca musical de um DJ no filesystem (Windows Explorer) por **gênero e
subgênero**, além de dimensões derivadas (BPM, tonalidade, energia), **sem quebrar** as
bibliotecas dos softwares de DJ.

## 2. Problema

Bibliotecas de DJ crescem sem estrutura: milhares de faixas espalhadas, nomes inconsistentes,
gêneros ausentes ou errados nas tags, e dependência de um software para "saber" o que é o quê.
Além disso, mover arquivos quebra bibliotecas:

- **file-centric** (Serato, Traktor, VirtualDJ) e **database-centric** (Rekordbox) guardam
  caminhos absolutos ou referências internas;
- hot cues e beatgrids vivem nesses bancos, não nos arquivos.

Portanto o organizador **não pode** reorganizar o filesystem de forma ingênua.

## 3. Princípios

1. **O catálogo é a fonte de verdade**, não as pastas. As pastas são uma *projeção*
   reorganizável do catálogo.
2. **O original nunca é destruído.** Estratégia padrão: hardlink + tags; nada é movido.
3. **Offline-first.** O núcleo funciona sem rede; fontes externas são enriquecimento opcional.
4. **Auditável e reversível.** Toda classificação guarda proveniência (`source` + `confidence`);
   toda reorganização gera plano (dry-run) e journal para undo.
5. **Nada é sobrescrito silenciosamente.** Conflitos viram decisão explícita do usuário.

## 4. Decisões fixadas

| # | Decisão | Valor |
|---|---|---|
| D1 | Interface | CLI em Python |
| D2 | Detecção de gênero | Tags/metadados **+** análise de áudio **+** serviço externo por fingerprint |
| D3 | Operação | Plano (dry-run) antes de aplicar |
| D4 | Escopo do MVP | Scanner + catálogo |
| D5 | Licença | Ferramenta **pessoal** (libera Essentia AGPL e modelos CC BY-NC) |
| D6 | Estratégia de arquivos | **hardlink + tags** (default); `move` como modo avançado opt-in |
| D7 | Softwares DJ alvo | **Serato**, **Rekordbox** e **filesystem genérico** |

Detalhamento e consequências: ver [decisoes.md](decisoes.md).

## 5. Escopo

**Dentro:**
- varredura e catálogo de bibliotecas (SQLite);
- leitura de tags (ID3/Vorbis/MP4) e gravação de tags próprias `DJLIFE_*`;
- classificação por gênero em camadas com proveniência e confiança;
- reorganização do filesystem via template, com plano/dry-run/apply/undo;
- relatórios (CSV/JSON) e estatísticas;
- integração com Rekordbox e Serato (leitura e relink).

**Fora (por ora):**
- player, mixer ou qualquer execução de áudio;
- edição de cues/beatgrids (apenas preservação/relink);
- sincronização em nuvem;
- interface gráfica.

## 6. Glossário

| Termo | Significado |
|---|---|
| **BPM** | batidas por minuto |
| **Key / tonalidade** | centro tonal; notações **Camelot** (`8A`) e **Open Key** (`8m`) |
| **Cue / hot cue** | marcador de posição na faixa, guardado pelo software de DJ |
| **Beatgrid** | grade de batidas ajustada manualmente, guardada pelo software |
| **Crate** | coleção de faixas (Serato) |
| **Fingerprint** | assinatura acústica (Chromaprint/AcoustID) que identifica a gravação |
| **Hardlink** | segundo caminho para o **mesmo** conteúdo; mover/criar não duplica dados |
| **Tag** | metadado embutido no arquivo (ID3, Vorbis comment, MP4 atom) |
| **Proveniência** | origem de uma classificação: `tags`, `rules`, `audio`, `fingerprint`, … |

## 7. Referências

- **beets** — referência conceitual (catálogo SQLite, path templates, plugin `duplicates`)
- **AcoustID / Chromaprint** — fingerprint
- **Discogs `styles`** — melhor fonte externa de subgênero (dataset CC0)
- **MusicBrainz** — identificação canônica (CC0)
- **Essentia / TempoCNN** — BPM e análise de áudio
- **CLAP / MERT / MuQ** — embeddings e classificação por aprendizado
