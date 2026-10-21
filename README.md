# paper-handler

Scaffold, render and manage academic papers with Quarto — Typst by default,
LaTeX when a journal template needs it. Ships as a Python CLI, an MCP server
for agents, *and* Nix modules, so the same corpus renders identically on a
laptop and on a server.

```console
$ paper-handler new graph-nets --title "Graph Neural Networks"
$ paper-handler render papers/graph-nets
$ paper-handler list
NAME        STATUS  ENGINE  RENDERED  TITLE
graph-nets  draft   typst   yes       Graph Neural Networks
```

## Why

A paper corpus is a directory tree of `.qmd` files, a `references.bib` and
whatever data they cite. Getting from that to a PDF usually means "install
Quarto, install Typst, hope the fonts resolve". paper-handler removes the
guesswork:

* **One toolchain derivation.** Quarto (which bundles Pandoc and Typst), an
  optional TeX Live scheme and an optional Jupyter kernel, in a single Nix
  package. `quarto render` works with no network and no separately-installed
  TeX.
* **Templates ship inside the package.** `paper-handler new` works offline on
  a fresh clone; a corpus can still add or override templates.
* **Configuration is layered and local.** `/etc` < XDG config < a corpus's own
  `paper-handler.toml` < `--config` < `PAPER_HANDLER_*`. Relative paths resolve
  against the file they came from, so a corpus stays self-describing.
* **Agent-native without a token tax.** The bundled MCP server exposes the
  outline/section/edit/lint loop as compact JSON tools, so a model can write a
  paper one section at a time instead of loading the whole document. It is
  stdlib-only and runs in the same derivation as the CLI.

## Install

### NixOS

```nix
{
  inputs.paper-handler.url = "github:Cairnstew/paper-handler";

  # ...
  imports = [ inputs.paper-handler.nixosModules.default ];
  my.programs.paper-handler = {
    enable = true;
    engine = "typst";       # or "latex" / "both"
    users = [ "seanc" ];    # write access to the shared corpus
  };
}
```

That puts the CLI, the MCP server (`paper-handler-mcp`) and the toolchain on
PATH system-wide, creates `/var/lib/paper-handler/papers` (mode 2775, group
`paper-handler`), writes `/etc/paper-handler/config.toml`, and optionally starts
a render timer with `render.enable = true`.

### Home Manager

```nix
{
  imports = [ inputs.paper-handler.homeManagerModules.default ];
  my.programs.paper-handler.enable = true;
}
```

For opencode, use the combined module instead — it imports the package module,
installs the CLI/toolchain and registers the MCP server, with an optional
researcher-python entry in the same import:

```nix
{
  imports = [ inputs.paper-handler.homeManagerModules.opencode ];

  my.programs.paper-handler-opencode = {
    enable = true;
    configFile = "${config.home.homeDirectory}/papers/paper-handler.toml";
    # Add this to register researcher-python-mcp alongside paper-handler-mcp:
    researcher.package =
      inputs.researcher-python.packages.${pkgs.system}.default;
  };
}
```

Both entries use a 120 s startup timeout; opencode's 5 s default is shorter
than a cold Nix shell. `researcher.package` is optional — if you import
researcher-python's own Home Manager module instead, leave it null so only one
module owns that entry.

### Bare / non-Nix

```console
$ nix run github:Cairnstew/paper-handler -- doctor
$ nix profile install github:Cairnstew/paper-handler
```

Or, with any Python ≥ 3.11 and a Quarto on PATH:

```console
$ pip install .
```

## Usage

| Command | What it does |
|---------|--------------|
| `paper-handler init [DIR]` | Start a corpus: `paper-handler.toml`, `_quarto.yml`, `papers/`. |
| `paper-handler new NAME` | Scaffold a paper from a template. `--engine`, `--template`, `--title`, `--force`. |
| `paper-handler render TARGET` | Render one paper. `--all` for the whole corpus, `--keep-going`, `-Q` to pass an argument through to Quarto. |
| `paper-handler list` | Corpus contents and render state. `--json` for scripting. |
| `paper-handler outline TARGET` | Heading tree and per-section word counts. `--json` for scripting. |
| `paper-handler lint TARGET` | Placeholders, heading jumps, long prose, undefined citations, readability. Exits 1 on errors. |
| `paper-handler meta get\|set KEY` | Read or edit YAML front matter. `set` parses YAML, so `set year 2026` stores a number. |
| `paper-handler templates list\|add` | Built-in and corpus templates; `add` installs a Quarto journal template. |
| `paper-handler bib init\|check` | Starter `references.bib`, and a structural check (brace balance, duplicate keys). |
| `paper-handler research import HANDOFF --paper NAME` | Create a paper from a researcher-python handoff bundle. |
| `paper-handler research context TARGET` | Counts, screening state, core papers and citation keys. |
| `paper-handler research status TARGET` | A handoff or imported paper's counts. |
| `paper-handler research sync TARGET --handoff DIR` | Refresh generated `research/` files without touching prose. |
| `paper-handler research prisma TARGET` | Append the generated PRISMA flow as a Quarto include. |
| `paper-handler doctor` | What of the toolchain is actually installed. `--json` for CI. |
| `paper-handler mcp` | Run the MCP server over stdio (same as `paper-handler-mcp`). |

Every render runs with the *paper's own directory* as the working directory,
so `bibliography: references.bib` and relative `include` paths resolve the way
you expect no matter where you invoked the CLI from.

### Templates

Built-in templates live at `paper_handler/templates/`:

| Template | Engine | Output |
|----------|--------|--------|
| `typst-article` | typst | `format: typst` |
| `latex-article` | latex | `format: pdf`, 11pt article class |
| `research-article` | typst | research-paper sections (Related Work, Limitations) |
| `literature-review` | typst | Introduction, Background, Themes, Synthesis, Gaps, Conclusion |

Put a directory of the same shape in `<papers_dir>/.templates/` (or set
`templates_dir`) to add your own; same-named corpus templates win.

Inside a template, `{{name}}`, `{{title}}`, `{{date}}`, `{{engine}}` and
`{{format}}` are substituted in `.qmd`/`.md`/`.yml`/`.bib`/`.typ`/`.tex`/`.toml`
files.

## MCP server

`paper-handler` speaks the [Model Context Protocol](https://modelcontextprotocol.io)
over stdio. The server is stdlib-only, so it ships inside the same Nix package
as the CLI — no extra Python closure, no daemon, no network.

```console
$ paper-handler-mcp        # standalone console script
$ paper-handler mcp        # same server, launched through the CLI
$ nix run .#mcp-server     # straight from the flake
```

| Flake output | What it is |
|--------------|------------|
| `packages.mcp-server` | The server binary (`paper-handler-mcp`) |
| `apps.mcp-server` | `nix run .#mcp-server` |
| `checks.mcp-protocol` | Drives the packaged server with real JSON-RPC in the sandbox |
| `homeManagerModules.opencode` | One import: CLI/toolchain + paper-handler MCP (+ optional researcher MCP) |

### Tools

Every tool returns compact JSON. Paper text never crosses the wire unless you
ask for one section.

| Tool | Use it for |
|------|------------|
| `paper_list` | Corpus index with status, engine and word counts. Start here. |
| `paper_context` | Budgeted context pack: outline, citations, issues, style rules. |
| `paper_outline` | Heading tree and per-section word counts. |
| `paper_read_section` | One section, truncated to `max_tokens`. |
| `paper_write_section` | `replace` / `append` / `insert` a section; returns a receipt, not the document. |
| `paper_write_abstract` | Set the front-matter abstract. |
| `paper_lint` | Placeholders, heading jumps, long prose, undefined citations, readability. |
| `paper_new` / `paper_init` | Scaffold a paper or a corpus. |
| `paper_render` | Render and get the PDF path, size and a short failure tail. |
| `paper_meta_get` / `paper_meta_set` | Read or edit front matter. |
| `paper_bib_check` / `paper_bib_init` | Bibliography hygiene. |
| `paper_templates` / `paper_doctor` | Discover templates and tools. |
| `paper_open_corpus` / `paper_close_corpus` | Pin a corpus for the session (for a server launched outside one). |
| `paper_research_import` | Scaffold a paper from a researcher-python handoff. |
| `paper_research_context` | Compact counts, core papers and citation keys. |
| `paper_research_sync` | Refresh generated `research/` files from a newer handoff. |
| `paper_cite_key` | Resolve a DOI/arXiv id/title to its BibTeX key. |
| `paper_research_prisma` | Insert/replace the PRISMA appendix include. |

Resources carry pull-based context:

* `paper://style-guide` — the house style (read once)
* `paper://corpus` — the corpus index
* `paper://templates` — available templates
* `paper://papers/{name}/outline` — one paper's outline
* `paper://papers/{name}/context` — one paper's budgeted context pack
* `paper://papers/{name}/research` — counts, screening state and citation keys

Prompts encode the writing loop: `write_paper`, `revise_paper`,
`review_paper`, and `research_to_paper` (handoff import → write → lint →
render).

### Client configuration

A generic local stdio server entry:

```json
{
  "mcp": {
    "paper-handler": {
      "type": "local",
      "command": ["paper-handler-mcp"],
      "enabled": true
    }
  }
}
```

For this repository's opencode setup, point at the flake output so the server
and its config stay pinned:

```nix
my.programs.opencode.mcp.paper-handler = {
  type = "local";
  command = [
    "${inputs.paper-handler.packages.${pkgs.system}.mcp-server}/bin/paper-handler-mcp"
  ];
};
```

The server discovers the corpus from its working directory, exactly like the
CLI. Launch it from a corpus root, or set `PAPER_HANDLER_CONFIG` to an
explicit `paper-handler.toml`.

### Writing loop

The intended low-token sequence is:

1. `paper_context` — outline, citations, current issues, style.
2. `paper_read_section` — only the section being changed.
3. `paper_write_section` — one section at a time.
4. `paper_lint` — fix errors, then warnings.
5. `paper_render` — once, at the end.

### Extending it

Adding a tool is one decorated function:

```python
@tool("paper_words", "Count words in one section.", schema({"heading": {"type": "string"}}))
def paper_words(args):
    ...
```

Put it in a module under `src/paper_handler/mcp/tools/` and import that module
from `tools/__init__.py`; the server discovers tools from the registry. Shared
document logic belongs in `paper_handler.documents` so the CLI can use it too.
Resources live in `mcp/resources.py`, prompts in `mcp/prompts.py`.

## Using with researcher-python

[`researcher-python`](https://github.com/Cairnstew/researcher-python) owns the
evidence half: search across arXiv/OpenAlex/Semantic Scholar/Crossref/PubMed,
screen with `core|general|excluded`, snowball citations, and render matrices and
PRISMA counts. `paper-handler` owns the manuscript half.

They meet at a **versioned handoff bundle**, not a Python dependency:

```console
$ researcher-python handoff research-out/cw1 --out research-out/cw1-handoff
$ paper-handler research import research-out/cw1-handoff --paper ai-governance \
      --title "AI Governance"
```

The bundle contains only the included records (default: `core` + `general`):

```
handoff/
  handoff.json          # schema_version, source, counts, screening, file index
  papers.json           # included records, export envelope
  references.bib        # included records only, unique keys
  citation-map.json     # DOI/arXiv id/folded title -> citation key
  matrix.md             # literature matrix with a cite_key column
  synthesis.md          # dimension x triage-label counts
  prisma.md             # screening flow
  README.md
```

Import creates the paper and copies the generated files under
`<paper>/research/`. The author keeps their own bibliography beside it:

```yaml
bibliography:
  - references.bib              # yours; never overwritten
  - research/references.bib     # generated; do not edit
```

That split is intentional. Re-running the researcher handoff and:

```console
$ paper-handler research sync papers/ai-governance --handoff research-out/cw1-handoff
```

refreshes `research/` and leaves the manuscript and your own entries alone.
Quarto/Pandoc accepts multiple bibliography files, so both sets of citations
resolve in one document.

The agent loop is:

1. `paper_research_import` (or the CLI above).
2. `paper_research_context` — counts, screening, top core papers, citation keys.
3. `paper_read_section` / `paper_write_section`, one section at a time.
4. `paper_cite_key` when you have a DOI/title but not the key.
5. `paper_lint`, then `paper_render`.

`paper_context` includes a small `research` block when a handoff is attached;
the full brief is only fetched on demand. The handoff schema is versioned
(`schema_version: 1`); a newer bundle is rejected with a clear message rather
than read incorrectly.

## Configuration

```toml
# paper-handler.toml — at the root of a corpus, or ~/.config/paper-handler/config.toml
engine = "typst"             # typst | latex | both
papers_dir = "papers"        # relative to this file
templates_dir = "templates"  # optional
```

Precedence, lowest first: `/etc/paper-handler/config.toml` →
`$XDG_CONFIG_HOME/paper-handler/config.toml` → the nearest
`paper-handler.toml` walking up from `$PWD` → `--config` /
`PAPER_HANDLER_CONFIG` → `PAPER_HANDLER_{ENGINE,PAPERS_DIR,TEMPLATES_DIR}`.

## Developing

```console
$ nix develop              # editable venv + full render toolchain
$ nix develop .#bootstrap  # python + uv only; run `uv lock` from here on a fresh clone
$ just test                # pytest
$ just mcp-test            # MCP registry + JSON-RPC/stdio tests
$ just render-example      # render papers/example
$ nix flake check          # pytest + module evals + MCP + handoff import/render
```

Dependency source of truth is `pyproject.toml` + `uv.lock`, consumed by
`uv2nix`. There is no dependency list in `flake.nix`.

## Layout

```
flake.nix          outputs: packages, overlays, both modules, checks, apps, devShells
nix/default.nix    the CLI/MCP package (uv2nix venv + mkApplication)
nix/toolchain.nix  Quarto + Typst/TeX Live + Jupyter, plus paper-toolchain-doctor
nix/module.nix     NixOS: my.programs.paper-handler
nix/home-module.nix Home Manager: my.programs.paper-handler
nix/opencode-module.nix  one-import opencode registration (CLI + MCP, optional researcher)
nix/checks.nix     nix flake check (MCP protocol + researcher handoff + render)
src/paper_handler/ CLI, document core, and MCP server
  documents.py     outline, section edits, citations, lint, readability
  research.py      read and attach a researcher-python handoff bundle
  templates/       typst-article, latex-article, research-article, literature-review
  mcp/registry.py  tool decorator + discovery
  mcp/tools/       corpus, writing, quality, build, research tools
  mcp/server.py    stdio JSON-RPC (tools, resources, prompts)
tests/             pytest suite (sandboxed: no /etc, no ambient PATH)
  fixtures/research-handoff/  a real bundle from researcher-python
```

## License

MIT.
