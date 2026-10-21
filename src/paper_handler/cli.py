"""The ``paper-handler`` command line.

Command layout:

* ``doctor``            what of the render toolchain is actually installed
* ``init``              start a corpus (config + Quarto project root)
* ``new``               scaffold a paper from a template
* ``render``            render one paper, or the whole corpus
* ``list``              what is in the corpus, and what has been rendered
* ``meta get|set``      read or edit a paper's YAML front matter
* ``templates list|add``  built-in / corpus templates, and Quarto journal ones
* ``bib init|check``    start and sanity-check a references.bib
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click

from paper_handler import __version__, documents, project, toolchain
from paper_handler import bib as bib_mod
from paper_handler import research as research_mod
from paper_handler.config import (
    ENGINES,
    Config,
    ConfigError,
    load_config,
    resolve_papers_dir,
)
from paper_handler.frontmatter import FrontMatterError
from paper_handler.frontmatter import read as read_front_matter
from paper_handler.frontmatter import write as write_front_matter
from paper_handler.project import CorpusExistsError, find_entry, init_corpus
from paper_handler.render import RenderError, render_many, render_path
from paper_handler.scaffold import ScaffoldError, list_templates, scaffold
from paper_handler.toolchain import ToolchainError


def _config(ctx: click.Context) -> Config:
    try:
        return load_config(config_path=ctx.obj.get("config_path"))
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


def _current_entry(explicit: Path | None) -> Path:
    """The entry document of the paper the user is standing in."""
    if explicit is not None:
        target = Path(explicit).expanduser()
        if target.is_dir():
            entry = find_entry(target)
            if entry is None:
                raise click.ClickException(f"{target}: no index.qmd or main.qmd found")
            return entry
        return target

    cwd = Path.cwd()
    entry = find_entry(cwd)
    if entry is not None:
        return entry
    raise click.ClickException(
        f"no paper in {cwd} — pass a file path, or run from inside a paper directory"
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="paper-handler")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    envvar="PAPER_HANDLER_CONFIG",
    help="Read settings from this TOML file instead of discovering them.",
)
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None) -> None:
    """Scaffold, render and manage academic papers with Quarto."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


# ── doctor ──────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def doctor(as_json: bool) -> None:
    """Report which parts of the render toolchain are available."""
    if as_json:
        click.echo(toolchain.doctor_json())
    else:
        click.echo(toolchain.doctor_text())
    if not toolchain.doctor_ok():
        raise SystemExit(1)


# ── mcp ─────────────────────────────────────────────────────────────────────


@cli.command()
def mcp() -> None:
    """Run the Model Context Protocol server over stdio.

    This is the same server as the `paper-handler-mcp` console script; it is
    here so an editor can launch the CLI it already has.
    """
    from paper_handler.mcp.server import main as mcp_main

    mcp_main([])


# ── init ────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument(
    "directory",
    type=click.Path(path_type=Path, file_okay=False),
    default=".",
    metavar="[DIRECTORY]",
)
@click.option("--engine", "-e", type=click.Choice(ENGINES), help="Default PDF engine.")
@click.option(
    "--papers-dir-name",
    default="papers",
    show_default=True,
    help="Name of the corpus directory to create.",
)
@click.option("--force", is_flag=True, help="Overwrite an existing paper-handler.toml.")
def init(directory: Path, engine: str | None, papers_dir_name: str, force: bool) -> None:
    """Initialise a paper corpus in DIRECTORY (defaults to the current one)."""
    try:
        created = init_corpus(
            directory, engine=engine, papers_dir_name=papers_dir_name, force=force
        )
    except CorpusExistsError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"initialised corpus in {created['directory']}")
    click.echo(f"  {Path(created['config']).name}   engine = {created['engine']}")
    click.echo("  _quarto.yml   quarto project root")
    click.echo(f"  {papers_dir_name}/        corpus")
    click.echo("")
    click.echo("Next: paper-handler new my-first-paper")


# ── new ─────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
@click.option(
    "--template",
    "-t",
    default=None,
    help="Template name (see `paper-handler templates list`).",
)
@click.option("--engine", "-e", type=click.Choice(ENGINES), help="PDF engine for this paper.")
@click.option("--title", default=None, help="Paper title (defaults to a title-cased name).")
@click.option(
    "--papers-dir",
    type=click.Path(path_type=Path, file_okay=False),
    help="Corpus directory (defaults to the configured papers_dir).",
)
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing paper directory.")
@click.pass_context
def new(
    ctx: click.Context,
    name: str,
    template: str | None,
    engine: str | None,
    title: str | None,
    papers_dir: Path | None,
    force: bool,
) -> None:
    """Create a new paper called NAME from a template."""
    config = _config(ctx)
    try:
        result = scaffold(
            name,
            config,
            template=template,
            engine=engine,
            title=title,
            papers_dir=papers_dir,
            force=force,
        )
    except (ScaffoldError, ConfigError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"created {result.paper.entry} (template: {result.template.name})")
    click.echo("")
    click.echo("Next:")
    click.echo(f"  paper-handler render {result.paper.dir}")
    click.echo(f"  quarto preview {result.paper.entry.name}   # from {result.paper.dir}")


# ── render ──────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("target", required=False, type=click.Path(path_type=Path))
@click.option("--all", "all_papers", is_flag=True, help="Render every paper in the corpus.")
@click.option("--engine", "-e", type=click.Choice(ENGINES), help="Override the configured engine.")
@click.option("--keep-going", "-k", is_flag=True, help="Continue past the first failure.")
@click.option(
    "--quarto-arg",
    "-Q",
    multiple=True,
    help="Extra argument passed straight through to `quarto render`.",
)
@click.pass_context
def render(
    ctx: click.Context,
    target: Path | None,
    all_papers: bool,
    engine: str | None,
    keep_going: bool,
    quarto_arg: tuple[str, ...],
) -> None:
    """Render TARGET (a paper directory or a .qmd), or the whole corpus with --all."""
    config = _config(ctx)
    effective_engine = engine or config.engine
    extra = tuple(quarto_arg)

    if all_papers and target is not None:
        raise click.ClickException("pass either a TARGET or --all, not both")

    if all_papers:
        corpus = resolve_papers_dir(config)
        papers = project.discover(corpus)
        if not papers:
            raise click.ClickException(f"no papers found in {corpus}")
        click.echo(f"rendering {len(papers)} paper(s) from {corpus} [{effective_engine}]")
        try:
            report = render_many(
                papers, engine=effective_engine, extra_args=extra, keep_going=keep_going
            )
        except (RenderError, ToolchainError) as exc:
            raise click.ClickException(str(exc)) from exc
        for paper in report.succeeded:
            click.echo(f"  ok    {paper.name}  ->  {paper.pdf.name}")
        for paper in report.failed:
            click.echo(f"  FAIL  {paper.name}", err=True)
        if not report.ok:
            raise click.ClickException(f"{len(report.failed)} of {report.count} failed")
        click.echo(f"rendered {report.count} paper(s)")
        return

    if target is None:
        cwd_entry = find_entry(Path.cwd())
        if cwd_entry is None:
            raise click.ClickException("pass a paper to render, or --all for the whole corpus")
        target = cwd_entry.parent

    try:
        status = render_path(target, engine=effective_engine, extra_args=extra)
    except (RenderError, ToolchainError) as exc:
        raise click.ClickException(str(exc)) from exc
    if status != 0:
        raise click.ClickException(f"quarto render failed with exit status {status}")
    click.echo(f"rendered {target} [{effective_engine}]")


# ── list ────────────────────────────────────────────────────────────────────


@cli.command(name="list")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_context
def list_papers(ctx: click.Context, as_json: bool) -> None:
    """List the papers in the corpus and their render state."""
    config = _config(ctx)
    corpus = resolve_papers_dir(config)
    papers = project.discover(corpus)

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "name": p.name,
                        "title": p.title,
                        "engine": p.engine,
                        "status": p.status,
                        "rendered": p.rendered,
                        "entry": str(p.entry),
                        "pdf": str(p.pdf),
                    }
                    for p in papers
                ],
                indent=2,
            )
        )
        return

    if not papers:
        click.echo(f"no papers in {corpus}")
        click.echo("create one with: paper-handler new <name>")
        return

    rows = [
        (p.name, p.status, p.engine, "yes" if p.rendered else "no", p.title) for p in papers
    ]
    headers = ("NAME", "STATUS", "ENGINE", "RENDERED", "TITLE")
    # Every column but TITLE is padded; the title is the last thing on the line
    # and does not need trailing space.
    widths = [max(len(str(row[i])) for row in [*rows, headers]) for i in range(len(headers))]
    template_ = "  ".join(f"{{:<{w}}}" for w in widths[:-1]) + "  {}"
    click.echo(template_.format(*headers))
    for row in rows:
        click.echo(template_.format(*row))


# ── outline ─────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("target", required=False, type=click.Path(path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def outline(target: Path | None, as_json: bool) -> None:
    """Show a paper's heading tree and word counts."""
    entry = _current_entry(target)
    text = entry.read_text(encoding="utf-8")
    pack = documents.outline(text)

    if as_json:
        click.echo(json.dumps(pack, indent=2))
        return

    click.echo(f"{pack['title'] or entry.stem}  [{pack['status']}]")
    abstract = pack["abstract_words"]
    click.echo(f"  {pack['words']} words" + (f", abstract {abstract}" if abstract else ""))
    for section in pack["sections"]:
        click.echo(f"  {'  ' * (section['level'] - 1)}{section['heading']}  ({section['words']})")
    if pack["missing"]:
        click.echo("  missing: " + ", ".join(pack["missing"]))


# ── lint ────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("target", required=False, type=click.Path(path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--max-issues", default=20, show_default=True, help="Cap printed issues.")
def lint(target: Path | None, as_json: bool, max_issues: int) -> None:
    """Check a paper's structure, prose and citations."""
    entry = _current_entry(target)
    bib_files = [
        path
        for path in (
            entry.parent / "references.bib",
            entry.parent / "research" / "references.bib",
        )
        if path.is_file()
    ]
    report = documents.lint(entry.read_text(encoding="utf-8"), bib_files)
    issues = report["issues"]
    report["issues"] = issues[:max_issues]
    report["omitted"] = max(0, len(issues) - max_issues)

    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        click.echo(
            f"{entry}: {report['errors']} error(s), {report['warnings']} warning(s)"
        )
        for issue in report["issues"]:
            where = issue.get("section") or (
                f"line {issue['line']}" if issue.get("line") else ""
            )
            suffix = f"  [{where}]" if where else ""
            click.echo(f"  {issue['severity']:<7} {issue['code']:<20} {issue['message']}{suffix}")
        if report["omitted"]:
            click.echo(f"  … {report['omitted']} more (raise --max-issues)")
        reading = report["readability"]
        click.echo(
            f"  {reading['words']} words, {reading['avg_sentence']} words/sentence"
            + (f", Flesch {reading['flesch']}" if reading["flesch"] is not None else "")
        )
    if report["errors"]:
        raise SystemExit(1)


# ── research ────────────────────────────────────────────────────────────────


def _paper_dir(target: Path) -> Path:
    path = Path(target).expanduser().resolve()
    if path.is_file():
        path = path.parent
    if find_entry(path) is None:
        raise click.ClickException(f"{path}: no index.qmd or main.qmd found")
    return path


def _research_for(target: Path) -> research_mod.Handoff:
    """A handoff attached to a paper, or a standalone bundle/workspace."""
    path = Path(target).expanduser().resolve()
    try:
        if path.is_dir() and find_entry(path) is not None:
            handoff = research_mod.load_paper_handoff(path)
            if handoff is None:
                raise click.ClickException(f"{path}: no research/handoff.json attached")
            return handoff
        return research_mod.load_handoff(path)
    except research_mod.ResearchError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.group()
def research() -> None:
    """Import and inspect a researcher-python handoff."""


@research.command("import")
@click.argument("handoff", type=click.Path(path_type=Path, exists=True))
@click.option("--paper", "name", required=True, help="new paper name")
@click.option("--title", default=None, help="paper title (defaults to the name)")
@click.option("--engine", "-e", type=click.Choice(ENGINES), help="PDF engine")
@click.option(
    "--template",
    default="research-article",
    show_default=True,
    help="template to scaffold before attaching the handoff",
)
@click.option("--force", "-f", is_flag=True, help="overwrite an existing paper")
@click.pass_context
def research_import(
    ctx: click.Context,
    handoff: Path,
    name: str,
    title: str | None,
    engine: str | None,
    template: str,
    force: bool,
) -> None:
    """Create a paper from a handoff bundle and wire its bibliographies."""
    config = _config(ctx)
    try:
        bundle = research_mod.load_handoff(handoff)
        result = scaffold(
            name,
            config,
            template=template,
            engine=engine,
            title=title,
            force=force,
        )
        receipt = research_mod.attach_to_paper(result.paper.dir, bundle)
    except (research_mod.ResearchError, ScaffoldError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"imported {receipt['included']} records into {result.paper.dir}")
    click.echo(f"  research:   {receipt['research']}")
    click.echo(f"  citation keys: {receipt['keys']}")
    click.echo(f"  bibliography: {', '.join(receipt['bibliography'])}")
    click.echo("")
    click.echo("Next: paper-handler research context " + str(result.paper.dir))


@research.command("context")
@click.argument("target", type=click.Path(path_type=Path, exists=True))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def research_context(target: Path, as_json: bool) -> None:
    """Show the compact evidence brief for a paper (or a handoff bundle)."""
    bundle = _research_for(target)
    data = research_mod.brief(bundle)
    if as_json:
        click.echo(json.dumps(data, indent=2))
        return
    click.echo(f"topic: {data['topic'] or '(not set)'}")
    click.echo(f"included: {data['included']}  screening ready: {data['screening']['ready']}")
    click.echo(f"citation keys: {data['key_count']}")
    for item in data["papers"]:
        click.echo(f"  {item['key']}  {item['year'] or '----'}  {item['title']}")
    click.echo("")
    click.echo(data["next"])


@research.command("status")
@click.argument("target", type=click.Path(path_type=Path, exists=True))
def research_status(target: Path) -> None:
    """Print counts and screening state for a handoff or an imported paper."""
    bundle = _research_for(target)
    click.echo(f"source: {bundle.root}")
    click.echo(f"topic: {bundle.topic or '(not set)'}")
    click.echo(f"included: {bundle.included}  screening ready: {bundle.screening_ready}")
    for label in ("core", "general", "excluded", "unreviewed"):
        click.echo(f"  {label}: {bundle.counts.get(label, 0)}")
    click.echo(f"citation keys: {len(bundle.keys())}")


@research.command("sync")
@click.argument("target", type=click.Path(path_type=Path, exists=True))
@click.option(
    "--handoff",
    "handoff_path",
    required=True,
    type=click.Path(path_type=Path, exists=True),
    help="handoff bundle to re-import",
)
def research_sync(target: Path, handoff_path: Path) -> None:
    """Refresh a paper's generated research files from a new handoff."""
    paper_dir = _paper_dir(target)
    try:
        bundle = research_mod.load_handoff(handoff_path)
        receipt = research_mod.attach_to_paper(paper_dir, bundle)
    except (research_mod.ResearchError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"synced {receipt['included']} records and {receipt['keys']} keys into "
        f"{receipt['research']}"
    )


@research.command("prisma")
@click.argument("target", type=click.Path(path_type=Path, exists=True))
@click.option("--heading", default="Screening", show_default=True, help="appendix heading")
@click.option("--after", default=None, help="insert after this section (default: end)")
def research_prisma(target: Path, heading: str, after: str | None) -> None:
    """Append the generated PRISMA flow to a paper as an included appendix."""
    paper_dir = _paper_dir(target)
    try:
        receipt = research_mod.append_prisma(
            paper_dir, heading=heading, after=after
        )
    except (research_mod.ResearchError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"{receipt['action']}ed '{receipt['heading']}' in {paper_dir} "
        f"(includes {receipt['include']})"
    )


# ── meta ────────────────────────────────────────────────────────────────────


@cli.group()
def meta() -> None:
    """Read or edit a paper's YAML front matter."""


@meta.command("get")
@click.argument("key")
@click.argument("file", required=False, type=click.Path(path_type=Path))
def meta_get(key: str, file: Path | None) -> None:
    """Print the value of KEY in FILE's front matter."""
    entry = _current_entry(file)
    try:
        data = read_front_matter(entry)
    except (FrontMatterError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    if key not in data:
        raise click.ClickException(f"{entry.name}: no {key!r} in front matter")
    value = data[key]
    click.echo(json.dumps(value) if isinstance(value, (dict, list)) else str(value))


@meta.command("set")
@click.argument("key")
@click.argument("value")
@click.argument("file", required=False, type=click.Path(path_type=Path))
def meta_set(key: str, value: str, file: Path | None) -> None:
    """Set KEY to VALUE in FILE's front matter.

    VALUE is parsed as YAML when possible, so `set year 2026` stores a number
    and `set keywords '[a, b]'` stores a list.
    """
    import yaml

    entry = _current_entry(file)
    try:
        data = read_front_matter(entry)
    except (FrontMatterError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        data[key] = yaml.safe_load(value)
    except yaml.YAMLError:
        data[key] = value
    try:
        write_front_matter(entry, data)
    except (FrontMatterError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{entry.name}: {key} = {data[key]}")


# ── templates ───────────────────────────────────────────────────────────────


@cli.group(name="templates")
def templates_group() -> None:
    """List templates, or install a Quarto journal template."""


@templates_group.command("list")
@click.pass_context
def templates_list(ctx: click.Context) -> None:
    """List built-in and corpus-local templates."""
    config = _config(ctx)
    templates = list_templates(config.effective_templates_dir)
    if not templates:
        click.echo("no templates found")
        return
    width = max(len(t.name) for t in templates)
    for template in templates:
        origin = "built-in" if template.builtin else "corpus  "
        click.echo(f"  {template.name:<{width}}  {origin}  {template.path}")


@templates_group.command("add")
@click.argument("spec")
def templates_add(spec: str) -> None:
    """Install a Quarto journal template, e.g. `quarto-journals/acm`.

    This shells out to `quarto use template`, which downloads from GitHub, so
    it needs network access and is never run implicitly.
    """
    try:
        quarto = toolchain.require("quarto")
    except ToolchainError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"running: quarto use template {spec}")
    status = subprocess.run([quarto, "use", "template", spec], check=False).returncode
    if status != 0:
        raise click.ClickException(f"quarto use template failed with exit status {status}")
    click.echo("installed — add `format:` for it to the new paper's front matter")


# ── bib ─────────────────────────────────────────────────────────────────────


@cli.group()
def bib() -> None:
    """Start and sanity-check a references.bib."""


@bib.command("init")
@click.argument("file", required=False, type=click.Path(path_type=Path))
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing file.")
def bib_init(file: Path | None, force: bool) -> None:
    """Create a starter references.bib (in the current paper by default)."""
    target = file if file is not None else _current_entry(None).parent / "references.bib"
    try:
        created = bib_mod.init(target, overwrite=force)
    except bib_mod.BibError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"wrote {created}")


@bib.command("check")
@click.argument("file", required=False, type=click.Path(path_type=Path))
def bib_check(file: Path | None) -> None:
    """Report structural problems in every bibliography a paper cites."""
    if file is not None:
        targets = [file]
    else:
        entry = _current_entry(None)
        targets = [
            path
            for path in (
                entry.parent / "references.bib",
                entry.parent / "research" / "references.bib",
            )
            if path.is_file()
        ] or [entry.parent / "references.bib"]

    failed = False
    for target in targets:
        problems = bib_mod.check(target)
        if not problems:
            click.echo(f"{target}: ok ({len(bib_mod.keys(target))} entries)")
            continue
        failed = True
        for problem in problems:
            click.echo(f"  {problem}", err=True)
    if failed:
        raise SystemExit(1)


def main() -> None:
    """Console-script entry point, with domain errors rendered uniformly."""
    try:
        cli(prog_name="paper-handler")
    except (ToolchainError, RenderError, ScaffoldError, bib_mod.BibError, ConfigError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1) from exc
