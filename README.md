# djLife

Catálogo e organização de biblioteca musical para DJs. Indexa seus arquivos em um **catálogo
SQLite** (fonte de verdade) e reorganiza o filesystem por gênero/subgênero **sem quebrar** as
bibliotecas Serato/Rekordbox — por padrão via **hardlink**, sem tocar nos originais.

Pipeline de classificação em camadas: tags (L0) → regras + taxonomia (L1) → DSP BPM/tonalidade
(L2) → embeddings CLAP + k-NN (L3) → aprendizado pelas correções (`learned`, L3.5) → foundation
models MERT/MuQ (L4).

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

# 3. Revisa manualmente faixas cujo gênero diverge entre as fontes (tags/regras/embeddings)
djlife review            # fila interativa; --list só lista, --limit N, --open abre no player

# 3b. Aprende com as correções do `review` (camada `learned`, k-NN sobre embeddings)
djlife learn             # dry-run; --apply grava `learned`; --explain N mostra os vizinhos

# 4. Visão geral e buscas
djlife stats
djlife search "deadmau5"

# 5. Organização: plano (dry-run) -> executa -> desfaz se quiser
djlife plan
djlife apply
djlife undo

# 6. Playlists M3U8 por gênero/subgênero (dry-run; --apply grava)
djlife export
djlife export --apply

# 7. Duplicatas e versões
djlife duplicates
djlife versions

# 8. Oferta premium planejada
djlife premium

# 9. Licenciamento offline do premium
djlife license machine-id
djlife license generate-keypair                 # --encrypt cifra a chave privada (passphrase)
djlife license issue --customer-id CLIENTE --plan lifetime --bind-current-machine
djlife license status

# 9b. Edição ADM/dona (aba de controle de usuários)
djlife license owner --customer-id DONA         # licença owner: todos os recursos liberados
djlife license list                             # lista as licenças emitidas (registro JSON)
djlife license renew RECORD_ID --days 30        # renova uma licença
djlife license revoke RECORD_ID                 # marca a licença como revogada

# 10. Importação online com yt-dlp (premium; exige licença)
djlife import "https://..."            # dry-run: lê os metadados
djlife import "https://..." --apply    # baixa para --out (padrão: downloads/)

# 11. Interface web local (Tech-Noir; catálogo só leitura; aba admin por token)
djlife ui

# 12. Diagnóstico do ambiente e do catálogo (somente leitura)
djlife doctor
```

Comandos que alteram arquivos ou bancos DJ são **dry-run por padrão** — `analyze`, `embed`,
`neighbors`, `learn`, `dedupe`, `export`, `import` e `relink` só executam com `--apply`. A
organização do filesystem segue o fluxo `plan` (dry-run) → `apply` (executa, pede confirmação) →
`undo` (reverte pelo journal). O `review` não é dry-run: grava a decisão do usuário no **catálogo**
(`source=manual`, que passa a valer sobre as fontes automáticas) e não toca o filesystem; o
`learn` reprocessa essas correções em uma camada `learned` (acima de `embedding`), também sem
tocar o filesystem. Lista completa: `djlife --help`.

> As integrações com **Rekordbox/Serato estão em beta** — não há garantia de funcionamento. O
> fluxo suportado e priorizado é a organização no **filesystem** (`plan`/`apply`).

---

## Extras opcionais

Instale apenas o que precisar (a instalação base já cobre o núcleo):

| Extra | Para quê | Instalação |
|---|---|---|
| `analysis` | BPM + tonalidade via `librosa` (L2) | `pip install -e ".[analysis]"` |
| `ml` | Embeddings CLAP/MERT + k-NN (L3/L4) | `pip install -e ".[ml]"` |
| `muq` | Embedder MuQ (L4, pesos CC-BY-NC) | `pip install -e ".[muq]"` |
| `fingerprint` | Duplicatas por fingerprint acústico (Chromaprint) | `pip install -e ".[fingerprint]"` |
| `rekordbox` | Ler/relink de `master.db` do Rekordbox 6/7 (beta) | `pip install -e ".[rekordbox]"` |
| `essentia` | Backend alternativo de análise (Linux/WSL2; sem wheel no Windows) | `pip install -e ".[essentia]"` |
| `packaging` | Gerar o executável com PyInstaller | `pip install -e ".[packaging]"` |
| `premium` | Base premium com importação online via `yt-dlp` | `pip install -e ".[premium]"` |
| `dev` | Testes, lint e tipagem (pytest/ruff/mypy) | `pip install -e ".[dev]"` |

Exemplo com a camada L3/L4:

```powershell
pip install -e ".[ml]"          # CLAP/MERT; use ".[muq]" para o MuQ
djlife embed                     # dry-run; --apply grava os vetores em `embeddings`
djlife embed --backend mert      # ou --backend muq (requer o extra correspondente)
djlife neighbors                 # dry-run; --apply propõe gênero para faixas sem rótulo
djlife learn                     # dry-run; --apply aprende com as correções (`source=manual`)
```

> O `essentia` não publica wheel para Windows e exige `python-ffmpeg`. No Windows use `librosa`
> (extra `analysis`), que é o backend padrão.

Exemplo com a camada premium preparada:

```powershell
pip install -e ".[premium]"
djlife premium
djlife import "https://..."            # recurso premium: exige licença válida
djlife import "https://..." --apply    # baixa o áudio; depois `djlife scan downloads/`
```

> A fase atual prepara os planos **mensal** e **vitalício** dentro do app e adiciona o extra
> opcional `yt-dlp`. A venda/liberação pode ser feita de forma **interpessoal/manual**, sem
> intermediário neste momento. O comando `djlife import` é o primeiro recurso **premium de
> fato**: ele consome o gate de licença (`premium.ytdlp_import`) e é bloqueado sem licença
> válida.

### Licença offline do premium

O premium agora suporta:

- **licença local assinada por Ed25519**
- **vínculo opcional por hash da máquina**
- **expiração** para plano mensal
- **verificação offline** no app

Fluxo sugerido:

```powershell
# 1. gerar chaves (faça isso uma vez e guarde a privada fora do app)
djlife license generate-keypair

# 2. no computador do cliente, obter o hash da máquina
djlife license machine-id

# 3. emitir a licença manualmente
djlife license issue --customer-id CLIENTE --plan monthly --days 30 --machine-hash HASH_DO_CLIENTE

# 4. conferir o status da licença carregada
djlife license status
```

Configuração opcional no `djlife.toml`:

```toml
[license]
public_key = "C:\\caminho\\license_public_key.pem"
license_file = "C:\\caminho\\license.json"
private_key = "C:\\caminho\\license_private_key.pem"   # só para emissão (ADM)
registry_file = "C:\\caminho\\licenses.json"           # registro das licenças emitidas
admin_token = "uma-passphrase-forte"                   # habilita a aba admin da UI
```

### Edição ADM/dona (aba de controle de usuários)

A dona (ADM) opera em **modo owner**: uma licença `plan = owner` cujo recurso é o curinga `*`,
liberando **todos** os recursos premium sem trava.

```powershell
# gerar o par de chaves já cifrando a privada (guarde a passphrase)
djlife license generate-keypair --encrypt

# instalar a licença owner na própria máquina (dona)
djlife license owner --customer-id DONA

# gerenciar o registro local de licenças
djlife license list
djlife license renew RECORD_ID --days 30
djlife license revoke RECORD_ID
```

A aba **admin** do `djlife ui` oferece a mesma gestão (emitir, renovar, revogar) pelo navegador.
Com `[license].admin_token` definido, abra a aba, informe o token e opere; sem token a
administração fica **desabilitada**. A regra de segurança (ADR-0021): o **catálogo musical
continua somente leitura** — as únicas escritas vindas da UI ocorrem em `/api/admin/*`,
autenticadas pelo header `X-Admin-Token`, e atingem apenas o **registro JSON de licenças** e os
arquivos de licença. O servidor segue escutando em `127.0.0.1`.

> **Revogação offline não é DRM.** Marcar uma licença como `revoked` atualiza o **registro da
> dona**, mas não desliga uma licença já entregue ao cliente — o app só verifica a assinatura
> offline. A revogação serve para o controle interno, não como desligamento remoto.

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
