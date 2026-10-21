"""Creating new papers from templates.

Templates ship *inside the installed package* (``paper_handler/templates``) so
``paper-handler new`` works with no network and no corpus-local setup.  A
corpus can add or override templates by putting a directory of the same shape
in ``templates_dir`` (``<papers_dir>/.templates`` by default).
"""

from __future__ import annotations

import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from paper_handler import frontmatter
from paper_handler.config import Config, resolve_papers_dir
from paper_handler.project import ENGINE_TO_FORMAT, Paper, _build, find_entry

#: Directories never copied out of a template.
IGNORE = shutil.ignore_patterns(
    "__pycache__",
    ".quarto",
    ".pytest_cache",
    "*_files",
    "*.pdf",
    ".git",
)

#: Files whose contents get placeholder substitution.
SUBSTITUTED_SUFFIXES = {".qmd", ".md", ".yml", ".yaml", ".bib", ".typ", ".tex", ".toml"}

#: Placeholders accepted inside template files.
_PLACEHOLDER = re.compile(r"\{\{\s*(name|title|date|engine|format)\s*\}\}")

#: Paper directory names: lowercase, digits and single dashes.  Anything else
#: would end up as a filesystem path, so reject it before it does.
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: Which built-in template an engine reaches for when none is named.
DEFAULT_TEMPLATE = {"typst": "typst-article", "latex": "latex-article", "both": "typst-article"}


class ScaffoldError(RuntimeError):
    """A paper could not be created."""


class TemplateNotFoundError(ScaffoldError):
    """The requested template does not exist."""


@dataclass(frozen=True)
class Template:
    name: str
    path: Path
    builtin: bool


def builtin_templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def list_templates(templates_dir: Path | None = None) -> list[Template]:
    """Built-in templates plus corpus-local ones, corpus entries winning."""
    found: dict[str, Template] = {}
    builtin = builtin_templates_dir()
    if builtin.is_dir():
        for child in sorted(builtin.iterdir()):
            if child.is_dir():
                found[child.name] = Template(child.name, child, builtin=True)
    if templates_dir is not None:
        templates_dir = Path(templates_dir)
        if templates_dir.is_dir():
            for child in sorted(templates_dir.iterdir()):
                if child.is_dir():
                    found[child.name] = Template(child.name, child, builtin=False)
    return sorted(found.values(), key=lambda t: t.name)


def get_template(name: str, templates_dir: Path | None = None) -> Template:
    available = list_templates(templates_dir)
    for template in available:
        if template.name == name:
            return template
    names = ", ".join(t.name for t in available) or "(none)"
    raise TemplateNotFoundError(f"unknown template {name!r}; available: {names}")


def _substitute(text: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        return values[match.group(1)]

    return _PLACEHOLDER.sub(repl, text)


def _make_writable(root: Path) -> None:
    """Give the owner write access to a freshly copied template tree.

    Built-in templates are read from ``/nix/store``, where everything is mode
    0555/0444.  ``copytree`` preserves those bits, so without this the
    scaffolded paper is immutable and placeholder substitution dies with
    ``EACCES`` — a failure that only reproduces from an installed package, never
    from a writable source checkout.
    """
    for path in (root, *root.rglob("*")):
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0))


@dataclass(frozen=True)
class ScaffoldResult:
    paper: Paper
    template: Template
    files: tuple[Path, ...]


def scaffold(
    name: str,
    config: Config,
    *,
    template: str | None = None,
    engine: str | None = None,
    title: str | None = None,
    papers_dir: Path | None = None,
    force: bool = False,
    today: str | None = None,
) -> ScaffoldResult:
    """Create ``<papers_dir>/<name>`` from a template and return the paper.

    *today* is injectable so tests do not have to assert on a real date.
    """
    if not _NAME.match(name):
        raise ScaffoldError(
            f"invalid paper name {name!r}: use lowercase letters, digits and dashes"
        )

    chosen_engine = engine or config.engine
    template_name = template or DEFAULT_TEMPLATE[chosen_engine]
    resolved_templates = config.effective_templates_dir
    source = get_template(template_name, resolved_templates)
    if not (source.path / "index.qmd").is_file():
        raise ScaffoldError(f"template {source.name!r} has no index.qmd")

    corpus = resolve_papers_dir(config, papers_dir)
    target = corpus / name
    if target.exists() and not force:
        raise ScaffoldError(f"{target} already exists (pass --force to overwrite)")

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source.path, target, ignore=IGNORE)
    _make_writable(target)

    values = {
        "name": name,
        "title": title or name.replace("-", " ").title(),
        "date": today or _today(),
        "engine": chosen_engine,
        "format": ENGINE_TO_FORMAT[chosen_engine],
    }

    written: list[Path] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file() or path.suffix not in SUBSTITUTED_SUFFIXES:
            continue
        original = path.read_text(encoding="utf-8")
        updated = _substitute(original, values)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
        written.append(path)

    # The title in front matter is authoritative; a scaffolded paper should
    # never ship with `{{title}}` in it even if the template forgot one.
    entry = find_entry(target)
    if entry is None:
        raise ScaffoldError(f"{target}: template produced no index.qmd")
    meta = frontmatter.read(entry)
    if title:
        meta["title"] = title
        frontmatter.write(entry, meta)

    return ScaffoldResult(
        paper=_build(target, entry, name),
        template=source,
        files=tuple(written),
    )


def _today() -> str:
    from datetime import date

    return date.today().isoformat()
