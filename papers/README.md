# papers/

The example corpus for this repository.  `paper-handler.toml` at the repo root
points the CLI here, so:

```console
$ paper-handler list
$ paper-handler render papers/example
```

`example/` is a real (tiny) Typst paper with a working bibliography — it is what
`just render-example` and the `render-smoke` flake check exercise, so it doubles
as a regression fixture.  Do not delete it without replacing it with something
equally renderable.

Your own papers go here too, one directory each:

```
papers/
├── example/
│   ├── index.qmd          # entry document
│   ├── references.bib
│   └── index.pdf          # build output — git-ignored
└── my-paper/
    └── ...
```

Start one with `paper-handler new my-paper`.

## Research-backed papers

`paper-handler research import <handoff> --paper NAME` writes the generated
researcher-python bundle to `NAME/research/` and adds it to the front matter as
a second bibliography:

```yaml
bibliography:
  - references.bib              # yours
  - research/references.bib     # generated; do not edit
```

Keep `references.bib` for your own additions. `research sync` refreshes only
the generated files; it never rewrites the manuscript or your entries.
