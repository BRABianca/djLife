from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress
from rich.table import Table

from djlife import (
    __version__,
    classifier,
    curation,
    db,
    dedupe,
    doctor,
    planner,
    playlists,
    quarantine,
    report,
    scanner,
    tags,
    taxonomy,
    versions,
)
from djlife import apply as apply_mod
from djlife import config as config_mod
from djlife.analysis.base import AnalysisUnavailable
from djlife.analysis.runner import (
    AnalyzePlan,
    AnalyzeResult,
    apply_plan,
    build_plan,
    load_analyzer,
)
from djlife.integrations import base as integrations_base
from djlife.integrations import rekordbox as rekordbox_int
from djlife.integrations import serato as serato_int
from djlife.integrations.base import (
    SOFTWARE_REKORDBOX,
    SOFTWARES,
    IntegrationUnavailable,
    RelinkPlan,
    RelinkResult,
    relink_plan,
    resolve_move_mapping,
)
from djlife.ml.base import EmbeddingUnavailable
from djlife.ml.neighbors import (
    NeighborPlan,
    NeighborResult,
)
from djlife.ml.neighbors import (
    apply_plan as apply_neighbor_plan,
)
from djlife.ml.neighbors import build_plan as build_neighbor_plan
from djlife.ml.runner import EmbedPlan, EmbedResult, embedder_version, load_embedder
from djlife.ml.runner import apply_plan as apply_embed_plan
from djlife.ml.runner import build_plan as build_embed_plan
from djlife.ui import server as ui_server

app = typer.Typer(
    name="djlife",
    help="Catalogo e organizacao de biblioteca musical para DJs.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"djlife {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Mostra a versao e sai.",
            is_eager=True,
            callback=_version_callback,
        ),
    ] = False,
) -> None:
    """djLife - catalogo e organizacao de biblioteca musical para DJs."""


@app.command()
def scan(
    roots: Annotated[
        list[Path] | None,
        typer.Argument(help="Raizes a varrer (padrao: library.roots da config)."),
    ] = None,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
    no_hash: Annotated[
        bool, typer.Option("--no-hash", help="Nao calcular hash de conteudo.")
    ] = False,
    skip_tags: Annotated[bool, typer.Option("--skip-tags", help="Nao ler metadados.")] = False,
) -> None:
    """Varre as raizes, atualiza o catalogo e indexa metadados."""
    cfg = config_mod.load_config(config)
    targets = list(roots) if roots else list(cfg.library.roots)
    if not targets:
        console.print("[red]Nenhuma raiz informada[/red] (argumento ou library.roots).")
        raise typer.Exit(code=1)

    absent = [root for root in targets if not root.exists()]
    for root in absent:
        console.print(f"[red]Raiz inexistente:[/red] {root}")
    if len(absent) == len(targets):
        raise typer.Exit(code=1)

    conn = db.open_catalog(cfg.db_path)
    table = Table(title=f"Scan - {cfg.db_path}")
    table.add_column("Raiz")
    table.add_column("Arquivos", justify="right")
    table.add_column("Novos", justify="right")
    table.add_column("Atualiz.", justify="right")
    table.add_column("Ausentes", justify="right")
    table.add_column("Erros", justify="right")

    indexed_total = 0
    for root in targets:
        if root in absent:
            continue
        outcome = scanner.scan(
            conn,
            root,
            extensions=cfg.library.extensions,
            hash_files=cfg.catalog.hash_files and not no_hash,
            hash_algorithm=cfg.catalog.hash_algorithm,
            follow_symlinks=cfg.library.follow_symlinks,
        )
        if not skip_tags and outcome.changed_ids:
            indexed, _ = tags.index_tags(conn, outcome.changed_ids)
            indexed_total += indexed
        table.add_row(
            str(root),
            str(outcome.seen),
            str(outcome.new),
            str(outcome.updated),
            str(outcome.missing),
            str(outcome.error_count),
        )

    console.print(table)
    if not skip_tags:
        console.print(f"Metadados indexados: {indexed_total}")
    conn.close()


@app.command()
def classify(
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Resolve genero em camadas (tags e regras) e grava track_genres."""
    cfg, conn = _open_catalog(config)

    taxonomy_path = cfg.classification.taxonomy
    if not Path(taxonomy_path).exists():
        taxonomy_path = str(taxonomy.default_taxonomy_path())
    try:
        tree = taxonomy.load_taxonomy(taxonomy_path)
        rules = classifier.load_rules(cfg.classification.local_taxonomy)
    except ValueError as exc:
        conn.close()
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    genres = taxonomy.sync(conn, tree)
    layers = tuple(layer for layer in cfg.classification.enable if layer in classifier.LAYERS)
    result = classifier.classify(conn, tree, rules, layers)
    conn.close()

    table = Table(title=f"Classify - taxonomia {tree.version}")
    table.add_column("Metrica")
    table.add_column("Valor", justify="right")
    table.add_row("Generos na arvore", str(genres))
    table.add_row("Camadas", ", ".join(layers) if layers else "-")
    table.add_row("Regras locais", str(len(rules)))
    table.add_row("Faixas", str(result.tracks))
    table.add_row("Via tags (L0)", str(result.tagged))
    table.add_row("Via regras (L1)", str(result.ruled))
    table.add_row("Nao resolvidas", str(result.unresolved))
    table.add_row("Novas em track_genres", str(result.inserted))
    console.print(table)


def _fmt_duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}"


def _open_catalog(config: Path) -> tuple[config_mod.Config, sqlite3.Connection]:
    cfg = config_mod.load_config(config)
    if not cfg.db_path.exists():
        console.print(f"[red]Catalogo inexistente:[/red] {cfg.db_path}. Rode `djlife scan`.")
        raise typer.Exit(code=1)
    return cfg, db.open_catalog(cfg.db_path)


@app.command()
def stats(
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Mostra estatisticas do catalogo (arquivos, cobertura de tags, duracao)."""
    _, conn = _open_catalog(config)

    data = report.collect_stats(conn)
    conn.close()

    summary = Table(title="Estatisticas")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Arquivos", str(data.files))
    summary.add_row("Faixas", str(data.tracks))
    summary.add_row("Ausentes", str(data.missing))
    summary.add_row("Erros", str(data.errors))
    summary.add_row("Duracao total", _fmt_duration(data.total_duration))
    console.print(summary)

    if data.by_extension:
        ext_table = Table(title="Por extensao")
        ext_table.add_column("Ext")
        ext_table.add_column("Arquivos", justify="right")
        for ext, total in data.by_extension:
            ext_table.add_row(ext, str(total))
        console.print(ext_table)

    coverage = Table(title="Cobertura de tags")
    coverage.add_column("Campo")
    coverage.add_column("Com valor", justify="right")
    coverage.add_column("Base", justify="right")
    coverage.add_column("%", justify="right")
    for label, filled, base in data.coverage:
        pct = (filled / base * 100) if base else 0.0
        coverage.add_row(label, str(filled), str(base), f"{pct:.1f}")
    console.print(coverage)


@app.command()
def search(
    term: Annotated[
        str, typer.Argument(help="Termo buscado em titulo, artista, album ou caminho.")
    ],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximo de resultados.")] = 50,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Busca faixas no catalogo por texto."""
    _, conn = _open_catalog(config)
    rows = report.search(conn, term, limit=limit)
    conn.close()

    if not rows:
        console.print("[yellow]Nenhum resultado.[/yellow]")
        raise typer.Exit(code=1)

    table = Table(title=f"Busca - {term!r}")
    table.add_column("Titulo")
    table.add_column("Artista")
    table.add_column("Album")
    table.add_column("Genero")
    table.add_column("Caminho")
    for row in rows:
        table.add_row(
            row.title or "-",
            row.artist or "-",
            row.album or "-",
            row.genre or "-",
            row.path,
        )
    console.print(table)
    console.print(f"Resultados: {len(rows)}")


def report_cmd(
    output: Annotated[Path, typer.Argument(help="Arquivo de saida (.csv ou .json).")],
    fmt: Annotated[
        str | None, typer.Option("--format", "-f", help="Formato (csv/json); padrao pela extensao.")
    ] = None,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Exporta o catalogo para CSV ou JSON."""
    _, conn = _open_catalog(config)
    try:
        count = report.export(conn, output, fmt=fmt)
    except ValueError as exc:
        conn.close()
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    conn.close()
    console.print(f"Exportadas {count} faixas para {output}")


app.command(name="report")(report_cmd)


def _print_export_plan(built: playlists.ExportPlan, preview: int) -> None:
    summary = Table(title=f"Export - {built.group_by} -> {built.out_dir}")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Playlists", str(len(built.playlists)))
    summary.add_row("Faixas", str(built.total))
    console.print(summary)

    if preview > 0 and built.playlists:
        shown = built.playlists[:preview]
        table = Table(title=f"Playlists ({len(shown)} de {len(built.playlists)})")
        table.add_column("Playlist")
        table.add_column("Faixas", justify="right")
        for playlist in shown:
            table.add_row(str(playlist.relative), str(len(playlist.tracks)))
        console.print(table)


def _print_export_result(result: playlists.ExportResult) -> None:
    summary = Table(title=f"Export - {result.out_dir}")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Playlists gravadas", str(result.playlists))
    summary.add_row("Faixas", str(result.tracks))
    summary.add_row("Erros", str(result.errors))
    console.print(summary)


@app.command()
def export(
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Diretorio de saida das playlists.")
    ] = None,
    by: Annotated[
        str, typer.Option("--by", help="Agrupar por genre ou subgenre (padrao: genre).")
    ] = "genre",
    apply: Annotated[
        bool, typer.Option("--apply", help="Grava os arquivos .m3u8 em disco.")
    ] = False,
    preview: Annotated[
        int, typer.Option("--preview", "-n", help="Playlists exibidas na previa.")
    ] = 20,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Gera playlists M3U8 por genero/subgenero a partir do catalogo (dry-run por padrao)."""
    cfg, conn = _open_catalog(config)
    destination = out
    if destination is None:
        if cfg.files.target is None:
            conn.close()
            console.print("[red]Defina files.target na config ou use --out.[/red]")
            raise typer.Exit(code=1)
        destination = Path(cfg.files.target) / "_playlists"

    try:
        built = playlists.build_plan(
            conn, out_dir=destination, group_by=by, unknown_dir=cfg.files.unknown_dir
        )
    except ValueError as exc:
        conn.close()
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    conn.close()

    _print_export_plan(built, preview)
    if not apply:
        return
    if not built.playlists:
        console.print("[yellow]Nada a exportar.[/yellow]")
        return

    result = playlists.write(built)
    _print_export_result(result)


def _resolve_target(cfg: config_mod.Config, override: Path | None) -> Path:
    target = Path(override) if override else cfg.files.target
    if target is None:
        console.print("[red]Defina files.target na config ou use --target.[/red]")
        raise typer.Exit(code=1)
    return target


def _resolve_strategy(override: str | None, default: str) -> str:
    strategy = override or default
    if strategy not in config_mod.FILE_STRATEGIES:
        console.print(
            f"[red]Estrategia invalida:[/red] {strategy}. Use "
            f"{', '.join(config_mod.FILE_STRATEGIES)}."
        )
        raise typer.Exit(code=1)
    return strategy


def _print_plan(built: planner.Plan, preview: int) -> None:
    summary = Table(title=f"Plano - {built.strategy} -> {built.target}")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Itens", str(len(built.items)))
    summary.add_row("Prontos", str(built.count(planner.STATUS_READY)))
    summary.add_row("Ja aplicados", str(built.count(planner.STATUS_EXISTS)))
    summary.add_row("Conflitos", str(built.count(planner.STATUS_CONFLICT)))
    summary.add_row("Nao classificados", str(built.count(planner.STATUS_UNCLASSIFIED)))
    console.print(summary)

    genres = Table(title="Por genero")
    genres.add_column("Genero")
    genres.add_column("Itens", justify="right")
    for name, total in built.by_genre:
        genres.add_row(name, str(total))
    console.print(genres)

    if preview > 0 and built.items:
        shown = built.items[:preview]
        items = Table(title=f"Previa ({len(shown)} de {len(built.items)})")
        items.add_column("Status")
        items.add_column("Origem")
        items.add_column("Destino")
        for item in shown:
            items.add_row(item.status, str(item.src), str(item.dst) if item.dst else "-")
        console.print(items)


@app.command()
def plan(
    target: Annotated[
        Path | None, typer.Option("--target", "-t", help="Diretorio de destino.")
    ] = None,
    strategy: Annotated[
        str | None, typer.Option("--strategy", "-s", help="hardlink, move ou tag_only.")
    ] = None,
    preview: Annotated[int, typer.Option("--preview", "-n", help="Itens exibidos na previa.")] = 20,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Mostra o plano de organizacao (dry-run), sem tocar no filesystem."""
    cfg, conn = _open_catalog(config)
    destination = _resolve_target(cfg, target)
    chosen = _resolve_strategy(strategy, cfg.files.strategy)
    built = planner.build_plan(
        conn,
        target=destination,
        template=cfg.files.template,
        unknown_dir=cfg.files.unknown_dir,
        strategy=chosen,
    )
    conn.close()
    _print_plan(built, preview)


def apply_cmd(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Nao pedir confirmacao.")] = False,
    no_tags: Annotated[bool, typer.Option("--no-tags", help="Nao gravar tags DJLIFE_*.")] = False,
    target: Annotated[
        Path | None, typer.Option("--target", "-t", help="Diretorio de destino.")
    ] = None,
    strategy: Annotated[
        str | None, typer.Option("--strategy", "-s", help="hardlink, move ou tag_only.")
    ] = None,
    preview: Annotated[int, typer.Option("--preview", "-n", help="Itens exibidos na previa.")] = 0,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Executa o plano (hardlink/move + tags DJLIFE_* + journal)."""
    cfg, conn = _open_catalog(config)
    destination = _resolve_target(cfg, target)
    chosen = _resolve_strategy(strategy, cfg.files.strategy)
    built = planner.build_plan(
        conn,
        target=destination,
        template=cfg.files.template,
        unknown_dir=cfg.files.unknown_dir,
        strategy=chosen,
    )
    _print_plan(built, preview)

    ready = built.count(planner.STATUS_READY)
    if ready == 0:
        conn.close()
        console.print("[yellow]Nada a aplicar.[/yellow]")
        return
    if not yes and not typer.confirm(f"Aplicar {ready} operacoes em {destination}?"):
        conn.close()
        console.print("Cancelado.")
        return

    result = apply_mod.apply(conn, built, write_tags=not no_tags)
    conn.close()

    summary = Table(title=f"Apply - lote {result.batch}")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Estrategia", result.strategy)
    summary.add_row("Hardlinks", str(result.linked))
    summary.add_row("Movidos", str(result.moved))
    summary.add_row("Tags gravadas", str(result.tagged))
    summary.add_row("Ignorados", str(result.skipped))
    summary.add_row("Erros", str(result.errors))
    console.print(summary)


app.command(name="apply")(apply_cmd)


@app.command()
def undo(
    batch: Annotated[
        str | None, typer.Option("--batch", "-b", help="Lote a reverter (padrao: ultimo).")
    ] = None,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Reverte um apply usando o journal."""
    cfg, conn = _open_catalog(config)
    result = apply_mod.undo(
        conn, batch, stop=cfg.files.target, quarantine_dir=cfg.files.quarantine_dir
    )
    conn.close()

    if result.batch is None:
        console.print("[yellow]Nada a reverter.[/yellow]")
        raise typer.Exit(code=1)

    summary = Table(title=f"Undo - lote {result.batch}")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Removidos", str(result.removed))
    summary.add_row("Restaurados", str(result.restored))
    summary.add_row("Tags removidas", str(result.untagged))
    summary.add_row("Erros", str(result.errors))
    console.print(summary)


@app.command()
def duplicates(
    fingerprint: Annotated[
        bool,
        typer.Option(
            "--fingerprint", help="Calcula e inclui fingerprints (Chromaprint) nos grupos."
        ),
    ] = False,
    preview: Annotated[
        int, typer.Option("--preview", "-n", help="Grupos exibidos na previa.")
    ] = 20,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Detecta duplicatas em 3 niveis: hash -> fingerprint -> ISRC/MBID."""
    _, conn = _open_catalog(config)

    if fingerprint:
        try:
            computed, errors = dedupe.compute_fingerprints(conn)
        except dedupe.FingerprintUnavailable as exc:
            conn.close()
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc
        console.print(f"Fingerprints calculados: {computed} (erros: {errors})")

    result = dedupe.find_duplicates(conn, use_fingerprint=fingerprint)
    conn.close()

    summary = Table(title="Duplicatas")
    summary.add_column("Nivel")
    summary.add_column("Grupos", justify="right")
    for kind, total in result.by_kind:
        summary.add_row(kind, str(total))
    summary.add_row("Redundantes", str(result.redundant))
    console.print(summary)

    if preview > 0 and result.groups:
        shown = result.groups[:preview]
        table = Table(title=f"Grupos ({len(shown)} de {len(result.groups)})")
        table.add_column("Nivel")
        table.add_column("Chave")
        table.add_column("Membros", justify="right")
        table.add_column("Keeper")
        for group in shown:
            keeper = next((m.path for m in group.members if m.is_keeper), "-")
            table.add_row(group.kind, group.key[:16], str(len(group.members)), keeper)
        console.print(table)


def versions_cmd(
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Classifica versoes (Original/Extended/Radio/Remix/Bootleg) por regras."""
    _, conn = _open_catalog(config)
    result = versions.classify_versions(conn)
    conn.close()

    table = Table(title="Versoes")
    table.add_column("Versao")
    table.add_column("Faixas", justify="right")
    for label, total in result.counts:
        table.add_row(label, str(total))
    console.print(table)
    console.print(f"Classificadas: {result.classified} de {result.tracks}")


app.command(name="versions")(versions_cmd)


def _print_analyze_plan(plan: AnalyzePlan, preview: int) -> None:
    summary = Table(title=f"Analyze - {plan.analyzer} ({plan.version})")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Arquivos", str(plan.files))
    summary.add_row("Ja analisados", str(plan.analyzed))
    summary.add_row("Pendentes", str(plan.pending))
    console.print(summary)

    if preview > 0 and plan.candidates:
        shown = plan.candidates[:preview]
        table = Table(title=f"Previa ({len(shown)} de {plan.pending})")
        table.add_column("Arquivo")
        for candidate in shown:
            table.add_row(candidate.path)
        console.print(table)


def _print_analyze_result(result: AnalyzeResult) -> None:
    summary = Table(title=f"Analyze - {result.analyzer} ({result.version})")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Analisados", str(result.analyzed))
    summary.add_row("Falhas", str(result.failed))
    console.print(summary)

    if result.errors:
        table = Table(title=f"Falhas ({min(len(result.errors), 10)} de {len(result.errors)})")
        table.add_column("Arquivo")
        table.add_column("Motivo")
        for path, message in result.errors[:10]:
            table.add_row(path, message)
        console.print(table)
        console.print("[dim]Falhas registradas em scan_errors.[/dim]")


@app.command()
def analyze(
    backend: Annotated[
        str | None,
        typer.Option("--backend", "-b", help="librosa ou essentia (padrao: analysis.backend)."),
    ] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Executa a analise e grava em audio_analysis.")
    ] = False,
    fast: Annotated[
        bool, typer.Option("--fast", help="Analisa so o inicio da faixa (triagem rapida).")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Reanalisa arquivos ja analisados.")
    ] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", "-n", help="Maximo de arquivos analisados.")
    ] = None,
    preview: Annotated[int, typer.Option("--preview", help="Itens exibidos na previa.")] = 20,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Extrai BPM e tonalidade (Camelot/Open Key) para audio_analysis (dry-run por padrao)."""
    cfg, conn = _open_catalog(config)
    name = backend or cfg.analysis.backend
    try:
        analyzer = load_analyzer(
            name, fast=fast or cfg.analysis.fast, fast_seconds=cfg.analysis.fast_seconds
        )
    except (AnalysisUnavailable, ValueError) as exc:
        conn.close()
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    plan = build_plan(conn, analyzer, limit=limit, force=force)
    _print_analyze_plan(plan, preview)
    if not apply:
        conn.close()
        return
    if plan.pending == 0:
        conn.close()
        console.print("[yellow]Nada a analisar.[/yellow]")
        return

    with Progress(console=console) as progress:
        task_id = progress.add_task(f"Analisando com {analyzer.name}", total=plan.pending)

        def tick(index: int, total: int, path: str) -> None:
            progress.update(task_id, advance=1, description=f"{index}/{total} {Path(path).name}")

        result = apply_plan(conn, plan, analyzer, on_progress=tick)

    conn.close()
    _print_analyze_result(result)


def _print_embed_plan(plan: EmbedPlan, preview: int) -> None:
    summary = Table(title=f"Embed - {plan.embedder} ({plan.version})")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Arquivos", str(plan.files))
    summary.add_row("Ja embeddados", str(plan.embedded))
    summary.add_row("Pendentes", str(plan.pending))
    console.print(summary)

    if preview > 0 and plan.candidates:
        shown = plan.candidates[:preview]
        table = Table(title=f"Previa ({len(shown)} de {plan.pending})")
        table.add_column("Arquivo")
        for candidate in shown:
            table.add_row(candidate.path)
        console.print(table)


def _print_embed_result(result: EmbedResult) -> None:
    summary = Table(title=f"Embed - {result.embedder} ({result.version})")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Embeddados", str(result.embedded))
    summary.add_row("Falhas", str(result.failed))
    console.print(summary)

    if result.errors:
        table = Table(title=f"Falhas ({min(len(result.errors), 10)} de {len(result.errors)})")
        table.add_column("Arquivo")
        table.add_column("Motivo")
        for path, message in result.errors[:10]:
            table.add_row(path, message)
        console.print(table)
        console.print("[dim]Falhas registradas em scan_errors.[/dim]")


@app.command()
def embed(
    backend: Annotated[
        str | None,
        typer.Option("--backend", "-b", help="clap, mert ou muq (padrao: ml.backend)."),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="ID do modelo (padrao: ml.model).")
    ] = None,
    window: Annotated[
        float | None,
        typer.Option("--window", help="Segundos de audio usados (padrao: ml.window_seconds)."),
    ] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Calcula os embeddings e grava em embeddings.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Recalcula arquivos ja embeddados.")
    ] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", "-n", help="Maximo de arquivos processados.")
    ] = None,
    preview: Annotated[int, typer.Option("--preview", help="Itens exibidos na previa.")] = 20,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Calcula embeddings de audio (camada L3/L4) para o catalogo (dry-run por padrao)."""
    cfg, conn = _open_catalog(config)
    name = backend or cfg.ml.backend
    chosen_model = model or cfg.ml.model
    window_seconds = window if window is not None else cfg.ml.window_seconds
    try:
        version = embedder_version(name, chosen_model)
    except ValueError as exc:
        conn.close()
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    plan = build_embed_plan(conn, name, version, limit=limit, force=force)
    _print_embed_plan(plan, preview)
    if not apply:
        conn.close()
        return
    if plan.pending == 0:
        conn.close()
        console.print("[yellow]Nada a embeddar.[/yellow]")
        return

    try:
        embedder = load_embedder(name, model=chosen_model, window_seconds=window_seconds)
    except (EmbeddingUnavailable, ValueError) as exc:
        conn.close()
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    with Progress(console=console) as progress:
        task_id = progress.add_task(f"Embeddando com {embedder.name}", total=plan.pending)

        def tick(index: int, total: int, path: str) -> None:
            progress.update(task_id, advance=1, description=f"{index}/{total} {Path(path).name}")

        result = apply_embed_plan(conn, plan, embedder, on_progress=tick)

    conn.close()
    _print_embed_result(result)


def _print_neighbor_plan(plan: NeighborPlan, preview: int) -> None:
    summary = Table(title=f"Neighbors - {plan.model} ({plan.model_version})")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Embeddados", str(plan.embedded))
    summary.add_row("Rotulados (ref)", str(plan.labeled))
    summary.add_row("Alvos", str(plan.targets))
    summary.add_row("Propostas", str(plan.pending))
    console.print(summary)

    if preview > 0 and plan.proposals:
        shown = plan.proposals[:preview]
        table = Table(title=f"Propostas ({len(shown)} de {plan.pending})")
        table.add_column("Faixa", justify="right")
        table.add_column("Genero")
        table.add_column("Confianca")
        table.add_column("Score", justify="right")
        table.add_column("Vizinhos", justify="right")
        for proposal in shown:
            table.add_row(
                str(proposal.track_id),
                proposal.genre,
                proposal.confidence,
                f"{proposal.score:.2f}",
                str(proposal.neighbors),
            )
        console.print(table)


def _print_neighbor_result(result: NeighborResult) -> None:
    summary = Table(title="Neighbors")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Propostas gravadas", str(result.written))
    summary.add_row("Ignoradas (ja existiam)", str(result.skipped))
    console.print(summary)


@app.command()
def neighbors(
    k: Annotated[
        int | None, typer.Option("--k", help="Vizinhos por faixa (padrao: ml.neighbors).")
    ] = None,
    min_similarity: Annotated[
        float | None,
        typer.Option("--min-similarity", help="Similaridade minima (padrao: ml.min_similarity)."),
    ] = None,
    backend: Annotated[
        str | None,
        typer.Option("--backend", "-b", help="clap, mert ou muq (padrao: ml.backend)."),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="ID do modelo (padrao: ml.model).")
    ] = None,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Grava as propostas em track_genres (source=embedding)."),
    ] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", "-n", help="Maximo de faixas alvo.")
    ] = None,
    preview: Annotated[int, typer.Option("--preview", help="Propostas exibidas na previa.")] = 20,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Propoe genero por k-NN sobre embeddings para faixas sem rotulo (dry-run por padrao)."""
    cfg, conn = _open_catalog(config)
    name = backend or cfg.ml.backend
    chosen_model = model or cfg.ml.model
    try:
        version = embedder_version(name, chosen_model)
    except ValueError as exc:
        conn.close()
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    plan = build_neighbor_plan(
        conn,
        name,
        version,
        k=k if k is not None else cfg.ml.neighbors,
        min_similarity=min_similarity if min_similarity is not None else cfg.ml.min_similarity,
        limit=limit,
    )
    _print_neighbor_plan(plan, preview)
    if not apply:
        conn.close()
        return
    if plan.pending == 0:
        conn.close()
        console.print("[yellow]Nenhuma proposta nova.[/yellow]")
        return

    result = apply_neighbor_plan(conn, plan)
    conn.close()
    _print_neighbor_result(result)


def dedupe_cmd(
    apply: Annotated[
        bool, typer.Option("--apply", help="Executa a quarentena (move os redundantes).")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Nao pedir confirmacao.")] = False,
    destination: Annotated[
        Path | None,
        typer.Option("--quarantine", "-q", help="Diretorio de quarentena."),
    ] = None,
    preview: Annotated[int, typer.Option("--preview", "-n", help="Itens exibidos na previa.")] = 20,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Planeja (dry-run) a quarentena de duplicatas, movendo sem deletar."""
    cfg, conn = _open_catalog(config)
    quarantine_dir = destination or cfg.files.quarantine_dir
    if quarantine_dir is None:
        conn.close()
        console.print("[red]Defina files.quarantine_dir ou use --quarantine.[/red]")
        raise typer.Exit(code=1)

    plan = quarantine.build_quarantine_plan(conn, quarantine_dir)
    _print_quarantine(plan, preview)

    if not apply:
        conn.close()
        return
    if plan.count == 0:
        conn.close()
        console.print("[yellow]Nada a colocar em quarentena.[/yellow]")
        return
    if not yes and not typer.confirm(f"Mover {plan.count} arquivos para {quarantine_dir}?"):
        conn.close()
        console.print("Cancelado.")
        return

    result = quarantine.apply_quarantine(conn, plan)
    conn.close()

    summary = Table(title=f"Dedupe - lote {result.batch}")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Movidos p/ quarentena", str(result.moved))
    summary.add_row("Erros", str(result.errors))
    console.print(summary)


app.command(name="dedupe")(dedupe_cmd)


def _print_quarantine(plan: quarantine.QuarantinePlan, preview: int) -> None:
    summary = Table(title=f"Quarentena - {plan.quarantine_dir}")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Itens", str(plan.count))
    summary.add_row("Espaco", _fmt_size(plan.bytes_reclaimable))
    console.print(summary)

    if preview > 0 and plan.items:
        shown = plan.items[:preview]
        table = Table(title=f"Previa ({len(shown)} de {plan.count})")
        table.add_column("Nivel")
        table.add_column("Arquivo")
        table.add_column("Keeper")
        for item in shown:
            table.add_row(item.kind, str(item.src), item.keeper or "-")
        console.print(table)


def _fmt_size(total: int) -> str:
    size = float(total)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _select_softwares(override: str | None) -> tuple[str, ...]:
    if override is None:
        return SOFTWARES
    if override not in SOFTWARES:
        console.print(f"[red]Software invalido:[/red] {override}. Use {', '.join(SOFTWARES)}.")
        raise typer.Exit(code=1)
    return (override,)


def _serato_db_path(cfg: config_mod.Config) -> Path:
    path = integrations_base.serato_db_path(cfg)
    if path is None:
        console.print("[red]Defina integrations.serato_db na config.[/red]")
        raise typer.Exit(code=1)
    return path


@app.command()
def status(
    software: Annotated[
        str | None, typer.Option("--software", "-s", help="rekordbox ou serato (padrao: ambos).")
    ] = None,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Verifica a integridade dos bancos DJ (BETA: itens que resolvem para arquivos)."""
    cfg = config_mod.load_config(config)
    console.print(
        "[dim]Integracoes Rekordbox/Serato estao em [bold]beta[/bold]:"
        " o funcionamento nao e garantido.[/dim]"
    )

    table = Table(title="Integridade das bibliotecas DJ (beta)")
    table.add_column("Software")
    table.add_column("Itens", justify="right")
    table.add_column("Resolvidos", justify="right")
    table.add_column("Ausentes", justify="right")
    missing: list[tuple[str, str]] = []
    failed = False
    for name in _select_softwares(software):
        try:
            report_data = integrations_base.dj_status(cfg, name)
        except IntegrationUnavailable as exc:
            console.print(f"[yellow]{name}: {exc}[/yellow]")
            table.add_row(name, "-", "-", "-")
            failed = True
            continue
        table.add_row(
            name, str(report_data.total), str(report_data.resolved), str(report_data.missing)
        )
        missing.extend((name, path) for path in report_data.samples)
    console.print(table)

    if missing:
        samples = Table(title="Amostra de ausentes")
        samples.add_column("Software")
        samples.add_column("Caminho")
        for name, path in missing:
            samples.add_row(name, path)
        console.print(samples)

    if failed:
        raise typer.Exit(code=1)


def _print_relink_plan(plan: RelinkPlan, preview: int) -> None:
    summary = Table(title=f"Relink - {plan.software}")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Ajustes", str(plan.count))
    console.print(summary)

    if preview > 0 and plan.changes:
        shown = plan.changes[:preview]
        table = Table(title=f"Previa ({len(shown)} de {plan.count})")
        table.add_column("Antes")
        table.add_column("Depois")
        for change in shown:
            table.add_row(change.old, change.new)
        console.print(table)


def _print_relink_result(result: RelinkResult) -> None:
    summary = Table(title=f"Relink - {result.software}")
    summary.add_column("Metrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Atualizados", str(result.applied))
    summary.add_row("Erros", str(result.errors))
    summary.add_row("Backup", str(result.backup) if result.backup else "-")
    if result.after is not None:
        summary.add_row("Ausentes apos", str(result.after.missing))
    console.print(summary)


@app.command()
def relink(
    software: Annotated[
        str | None, typer.Option("--software", "-s", help="rekordbox ou serato (padrao: ambos).")
    ] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Executa o relink (com backup automatico).")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Nao pedir confirmacao.")] = False,
    preview: Annotated[
        int, typer.Option("--preview", "-n", help="Ajustes exibidos na previa.")
    ] = 20,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Aponta os bancos DJ para os destinos atuais do catalogo (BETA, dry-run por padrao)."""
    cfg, conn = _open_catalog(config)
    console.print(
        "[dim]Integracoes Rekordbox/Serato estao em [bold]beta[/bold]:"
        " o funcionamento nao e garantido.[/dim]"
    )
    try:
        mapping = resolve_move_mapping(conn)
    finally:
        conn.close()

    if not mapping:
        console.print("[yellow]Nenhum move no journal; nada a relinkar.[/yellow]")
        return

    roots = integrations_base.library_roots(cfg)
    failed = False
    for name in _select_softwares(software):
        try:
            if name == SOFTWARE_REKORDBOX:
                db_path = cfg.integrations.rekordbox_db
                if db_path is None:
                    console.print("[red]Defina integrations.rekordbox_db na config.[/red]")
                    failed = True
                    continue
                plan = relink_plan(
                    name,
                    rekordbox_int.read_tracks(db_path),
                    mapping,
                    convert=rekordbox_int.to_stored,
                )
            else:
                db_path = _serato_db_path(cfg)
                tracks = serato_int.read_tracks(db_path, roots=roots)
                plan = relink_plan(
                    name,
                    tracks,
                    mapping,
                    convert=lambda new, old: serato_int.to_stored(new, old, roots),
                )
        except IntegrationUnavailable as exc:
            console.print(f"[yellow]{name}: {exc}[/yellow]")
            failed = True
            continue

        _print_relink_plan(plan, preview)
        if not apply or plan.count == 0:
            continue
        if not yes and not typer.confirm(f"Atualizar {plan.count} caminhos no {name}?"):
            console.print("Cancelado.")
            continue

        if name == SOFTWARE_REKORDBOX:
            result = rekordbox_int.relink(db_path, plan, apply=True)
        else:
            result = serato_int.relink(db_path, plan, roots=roots, apply=True)
        _print_relink_result(result)

    if failed:
        raise typer.Exit(code=1)


_DOCTOR_TONE = {
    "ok": "[green]ok[/green]",
    "warn": "[yellow]warn[/yellow]",
    "fail": "[red]fail[/red]",
}


def doctor_cmd(
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Audita o ambiente e a organizacao do catalogo (somente leitura)."""
    cfg = config_mod.load_config(config)
    checks = doctor.run(cfg)

    table = Table(title="Doctor")
    table.add_column("Verificacao")
    table.add_column("Estado")
    table.add_column("Detalhe")
    for check in checks:
        tone = _DOCTOR_TONE.get(check.status, check.status)
        table.add_row(escape(check.name), tone, escape(check.detail))
    console.print(table)

    if any(check.status == doctor.FAIL for check in checks):
        raise typer.Exit(code=1)


app.command(name="doctor")(doctor_cmd)


_LEVEL_TONE = {
    curation.LEVEL_DIVERGENTE: "[red]divergente[/red]",
    curation.LEVEL_AMBIGUA: "[yellow]ambigua[/yellow]",
}


def _open_path(path: str) -> None:
    """Abre o arquivo no aplicativo padrao do sistema (best-effort)."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["cmd", "/c", "start", "", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as exc:
        console.print(f"  [red]Nao foi possivel abrir: {exc}[/red]")


def _search_choices(choices: list[curation.Choice], needle: str) -> list[curation.Choice]:
    return [
        choice
        for choice in choices
        if needle in choice.label.casefold() or needle in choice.slug.casefold()
    ]


def _print_choices(choices: list[curation.Choice]) -> None:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Genero")
    for index, choice in enumerate(choices, start=1):
        table.add_row(str(index), f"{escape(choice.label)} [dim]({escape(choice.slug)})[/dim]")
    console.print(table)


def _print_review_item(item: curation.ReviewItem) -> None:
    title = item.title or Path(item.path).stem
    console.print(f"[bold]{escape(item.artist or '')}[/bold] - {escape(title)}")
    console.print(f"[dim]{escape(item.path)}[/dim]")
    for signal in item.signals:
        console.print(f"  {signal.source:<9} {escape(signal.label)} [dim]({signal.confidence})[/dim]")
    suggestion = escape(item.suggestion.label)
    console.print(f"  [yellow]{item.level}[/yellow] -> sugestao: [bold]{suggestion}[/bold]")


def _print_review_queue(items: list[curation.ReviewItem], preview: int = 20) -> None:
    if not items:
        console.print("[green]Nenhum conflito de genero entre as fontes.[/green]")
        return
    table = Table(title=f"Curadoria - {len(items)} faixa(s) com conflito")
    table.add_column("#", justify="right")
    table.add_column("Faixa")
    table.add_column("Sinais")
    table.add_column("Nivel")
    for index, item in enumerate(items[:preview], start=1):
        signals = "\n".join(
            f"{signal.source}: {signal.label} ({signal.confidence})" for signal in item.signals
        )
        label = f"{item.artist or '-'} - {item.title or Path(item.path).stem}"
        table.add_row(
            str(index), escape(label), escape(signals), _LEVEL_TONE.get(item.level, item.level)
        )
    console.print(table)
    if len(items) > preview:
        console.print(f"[dim]... e mais {len(items) - preview} faixa(s); use --limit.[/dim]")


def _apply_choice(
    conn: sqlite3.Connection, item: curation.ReviewItem, genre_id: int, label: str
) -> str:
    curation.record_decision(conn, item.track_id, genre_id)
    console.print(f"  [green]ok[/green] -> {escape(label)}")
    return "assigned"


def _decide(
    conn: sqlite3.Connection, item: curation.ReviewItem, choices: list[curation.Choice]
) -> str:
    shown: list[curation.Choice] = []
    while True:
        answer = typer.prompt(
            "[Enter]=sugestao  [p] abrir  [s] pular  [k] manter  [q] sair  |  numero ou busca",
            default="",
            show_default=False,
        ).strip()
        low = answer.lower()
        if low == "q":
            return "quit"
        if low == "s":
            return "skipped"
        if low == "p":
            _open_path(item.path)
            continue
        if low in ("", "k"):
            suggestion = item.suggestion
            return _apply_choice(conn, item, suggestion.genre_id, suggestion.label)
        if answer.isdigit():
            position = int(answer)
            if 1 <= position <= len(shown):
                chosen = shown[position - 1]
                return _apply_choice(conn, item, chosen.genre_id, chosen.label)
            console.print("  [red]Numero fora da lista exibida.[/red]")
            continue
        matches = _search_choices(choices, low)
        if not matches:
            console.print("  [red]Nenhum genero corresponde; tente outro termo.[/red]")
            continue
        if len(matches) == 1:
            return _apply_choice(conn, item, matches[0].genre_id, matches[0].label)
        shown = matches
        _print_choices(shown)
        continue


def _run_review(
    conn: sqlite3.Connection,
    items: list[curation.ReviewItem],
    choices: list[curation.Choice],
    *,
    open_audio: bool,
) -> None:
    total = len(items)
    decided = 0
    skipped = 0
    for index, item in enumerate(items, start=1):
        console.rule(f"[bold cyan]{index}/{total}[/bold cyan]")
        _print_review_item(item)
        if open_audio:
            _open_path(item.path)
        try:
            outcome = _decide(conn, item, choices)
        except (KeyboardInterrupt, typer.Abort):
            console.print()
            break
        if outcome == "quit":
            break
        if outcome == "assigned":
            decided += 1
        else:
            skipped += 1
    console.print(f"[green]Decisoes gravadas:[/green] {decided} | [dim]sem decisao:[/dim] {skipped}")


@app.command()
def review(
    list_only: Annotated[
        bool, typer.Option("--list", help="Somente lista a fila de conflitos, sem revisar.")
    ] = False,
    limit: Annotated[
        int, typer.Option("--limit", "-n", help="Revisa no maximo N faixas (0 = todas).")
    ] = 0,
    open_audio: Annotated[
        bool, typer.Option("--open", help="Abre cada faixa no player padrao ao revisar.")
    ] = False,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Revisa manualmente as faixas cujo genero diverge entre as fontes (tags/regras/embeddings)."""
    _, conn = _open_catalog(config)
    try:
        items = curation.build_queue(conn)
        if limit > 0:
            items = items[:limit]
        _print_review_queue(items)
        if list_only or not items:
            return
        choices = curation.genre_choices(conn)
        if not choices:
            console.print("[yellow]Taxonomia vazia; rode `djlife scan` para carregar os generos.[/yellow]")
            return
        _run_review(conn, items, choices, open_audio=open_audio)
    finally:
        conn.close()


@app.command()
def ui(
    port: Annotated[
        int, typer.Option("--port", "-p", help="Porta do servidor (0 = aleatoria).")
    ] = 8765,
    host: Annotated[str, typer.Option("--host", help="Interface de escuta.")] = "127.0.0.1",
    no_open: Annotated[
        bool, typer.Option("--no-open", help="Nao abrir o navegador automaticamente.")
    ] = False,
    config: Annotated[Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")] = Path(
        "djlife.toml"
    ),
) -> None:
    """Sobe a interface web local (cyberpunk) para explorar o catalogo."""
    cfg = config_mod.load_config(config)

    def announce(url: str) -> None:
        console.print(f"[cyan]Interface djLife[/cyan] em [bold]{url}[/bold]")
        console.print(f"Catalogo: {cfg.db_path}")
        console.print("[dim]Ctrl+C para encerrar.[/dim]")

    ui_server.serve(cfg, host=host, port=port, open_browser=not no_open, on_ready=announce)


if __name__ == "__main__":
    app()
