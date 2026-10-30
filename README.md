# djLife

Catálogo e organização de biblioteca musical para DJs. Indexa seus arquivos em um **catálogo
SQLite** (fonte de verdade) e reorganiza o filesystem por gênero/subgênero **sem quebrar** as
bibliotecas Serato/Rekordbox — por padrão via **hardlink**, sem tocar nos originais.

Pipeline de classificação em camadas: tags (L0) → regras + taxonomia (L1) → DSP BPM/tonalidade
(L2) → embeddings CLAP + k-NN (L3) → foundation models MERT/MuQ (L4).

---

## Requisitos

- **Python 3.11+** (apenas para rodar do código-fonte; o executável dispensa Python)
- Windows, Linux ou macOS
- FFmpeg — **opcional**, só para os backends de áudio (`analysis`/`ml`)

---

## Download e instalação

### Opção 1 — Executável pronto (sem instalar Python)

Gere o binário portátil uma vez e use-o diretamente:

```powershell
git clone https://github.com/BRABianca/djLife.git
cd djLife
python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -e ".[packaging]"
pyinstaller packaging/djlife.spec
```

O resultado fica em `dist/djlife/` (~24 MB). Rode sem o venv:

```powershell
.\dist\djlife\djlife.exe --version
.\dist\djlife\djlife.exe --help
```

> O executável embute apenas o **núcleo** (scan, tags, classificação, plano/apply, dedupe,
> relatório, UI, status/relink de banco DJ). As camadas de áudio/embeddings e integrações de
> DJ ficam como extras **on-demand** (ver *Extras opcionais*).

### Opção 2 — Do código-fonte (recomendado para uso completo)

```powershell
git clone https://github.com/BRABianca/djLife.git
cd djLife
python -m venv .venv
.venv\Scripts\Activate.ps1        # Linux/macOS: source .venv/bin/activate

pip install -e .
djlife --version
```

---

## Uso rápido

```powershell
# 1. Varre as raízes e indexa metadados (tags) no catálogo
djlife scan "D:\MinhaMusica"

# 2. Resolve gênero em camadas (tags + regras) -> track_genres
djlife classify

# 3. Visão geral e buscas
djlife stats
djlife search "deadmau5"

# 4. Organização: plano (dry-run) -> executa -> desfaz se quiser
djlife plan
djlife apply
djlife undo

# 5. Duplicatas e versões
djlife duplicates
djlife versions

# 6. Interface web local (cyberpunk, somente leitura)
djlife ui
```

Comandos que alteram arquivos ou bancos DJ são **dry-run por padrão** — `analyze`, `embed`,
`neighbors`, `dedupe` e `relink` só executam com `--apply`. A organização do filesystem segue o
fluxo `plan` (dry-run) → `apply` (executa, pede confirmação) → `undo` (reverte pelo journal).
Lista completa: `djlife --help`.

---

## Extras opcionais

Instale apenas o que precisar (a instalação base já cobre o núcleo):

| Extra | Para quê | Instalação |
|---|---|---|
| `analysis` | BPM + tonalidade via `librosa` (L2) | `pip install -e ".[analysis]"` |
| `ml` | Embeddings CLAP/MERT + k-NN (L3/L4) | `pip install -e ".[ml]"` |
| `muq` | Embedder MuQ (L4, pesos CC-BY-NC) | `pip install -e ".[muq]"` |
| `fingerprint` | Duplicatas por fingerprint acústico (Chromaprint) | `pip install -e ".[fingerprint]"` |
| `rekordbox` | Ler/relink de `master.db` do Rekordbox 6/7 | `pip install -e ".[rekordbox]"` |
| `essentia` | Backend alternativo de análise (Linux/WSL2; sem wheel no Windows) | `pip install -e ".[essentia]"` |
| `packaging` | Gerar o executável com PyInstaller | `pip install -e ".[packaging]"` |
| `dev` | Testes, lint e tipagem (pytest/ruff/mypy) | `pip install -e ".[dev]"` |

Exemplo com a camada L3/L4:

```powershell
pip install -e ".[ml]"          # CLAP/MERT; use ".[muq]" para o MuQ
djlife embed                     # dry-run; --apply grava os vetores em `embeddings`
djlife embed --backend mert      # ou --backend muq (requer o extra correspondente)
djlife neighbors                 # dry-run; --apply propõe gênero para faixas sem rótulo
```

> O `essentia` não publica wheel para Windows e exige `python-ffmpeg`. No Windows use `librosa`
> (extra `analysis`), que é o backend padrão.

---

## Configuração

Copie o exemplo e ajuste as raízes da biblioteca:

```powershell
Copy-Item djlife.toml.example djlife.toml
```

```toml
[library]
roots = ["D:\\MinhaMusica"]
extensions = [".mp3", ".flac", ".wav", ".m4a"]
```

Seções disponíveis: `[library]`, `[catalog]`, `[classification]`, `[files]`, `[integrations]`,
`[analysis]`, `[ml]`. Sem o arquivo, o djLife usa os padrões. Salve em **UTF-8 sem BOM**.

---

## Desenvolvimento

```powershell
pip install -e ".[dev]"
pytest
ruff check src tests
mypy
```

---

## Documentação

- [Concepção](docs/concepcao.md) — objetivo e escopo
- [Arquitetura](docs/arquitetura.md) — componentes, pipeline L0→L4, schema
- [Roadmap](docs/roadmap.md) — fases
- [Decisões (ADR)](docs/decisoes.md) — histórico de decisões técnicas

---

## Licença

Ferramenta **de uso pessoal** (ver [ADR-0001](docs/decisoes.md)). Parte do ecossistema
(Essentia = AGPL-3.0; modelos de gênero = CC BY-NC) não é compatível com produto comercial.
