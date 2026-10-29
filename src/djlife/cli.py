from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from djlife import (
    __version__,
    classifier,
    db,
    dedupe,
    planner,
    quarantine,
    report,
    scanner,
    tags,
    taxonomy,
    versions,
)
from djlife import apply as apply_mod
from djlife import config as config_mod
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
    no_hash: Annotated[
        bool, typer.Option("--no-hash", help="Nao calcular hash de conteudo.")
    ] = False,
    skip_tags: Annotated[
        bool, typer.Option("--skip-tags", help="Nao ler metadados.")
    ] = False,
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
    preview: Annotated[
        int, typer.Option("--preview", "-n", help="Itens exibidos na previa.")
    ] = 20,
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Nao pedir confirmacao.")
    ] = False,
    no_tags: Annotated[
        bool, typer.Option("--no-tags", help="Nao gravar tags DJLIFE_*.")
    ] = False,
    target: Annotated[
        Path | None, typer.Option("--target", "-t", help="Diretorio de destino.")
    ] = None,
    strategy: Annotated[
        str | None, typer.Option("--strategy", "-s", help="hardlink, move ou tag_only.")
    ] = None,
    preview: Annotated[
        int, typer.Option("--preview", "-n", help="Itens exibidos na previa.")
    ] = 0,
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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


def dedupe_cmd(
    apply: Annotated[
        bool, typer.Option("--apply", help="Executa a quarentena (move os redundantes).")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Nao pedir confirmacao.")
    ] = False,
    destination: Annotated[
        Path | None,
        typer.Option("--quarantine", "-q", help="Diretorio de quarentena."),
    ] = None,
    preview: Annotated[
        int, typer.Option("--preview", "-n", help="Itens exibidos na previa.")
    ] = 20,
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
) -> None:
    """Verifica a integridade dos bancos DJ (itens que resolvem para arquivos existentes)."""
    cfg = config_mod.load_config(config)

    table = Table(title="Integridade das bibliotecas DJ")
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
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
) -> None:
    """Aponta os bancos DJ para os destinos atuais do catalogo (dry-run por padrao)."""
    cfg, conn = _open_catalog(config)
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


@app.command()
def ui(
    port: Annotated[
        int, typer.Option("--port", "-p", help="Porta do servidor (0 = aleatoria).")
    ] = 8765,
    host: Annotated[str, typer.Option("--host", help="Interface de escuta.")] = "127.0.0.1",
    no_open: Annotated[
        bool, typer.Option("--no-open", help="Nao abrir o navegador automaticamente.")
    ] = False,
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Arquivo de configuracao.")
    ] = Path("djlife.toml"),
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
