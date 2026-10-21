# nix/toolchain.nix — the render toolchain shipped alongside the CLI.
#
#   nix build .#toolchain
#   nix run  .#doctor
#
# One derivation that puts Quarto (which bundles Pandoc and its own Typst) plus
# the selected PDF engine on PATH, so `quarto render` works with no network and
# no separately-installed TeX.  The CLI itself is deliberately *not* part of
# this: a consumer may want to pin a different CLI than toolchain.
#
# `engine`:
#   "typst" — Typst only.  Fast compilation, nice error messages, and what
#             Quarto's `format: typst` drives.  Smallest closure.  Typst ships
#             its own default text face, so no system fonts are required.
#   "latex" — TeX Live instead of Typst, for journal templates that ship LaTeX
#             classes (ACM, IEEE, Elsevier, ...).  Much larger closure.
#   "both"  — ship both engines.
#
# `notebook` adds a Jupyter kernel so executable ```python cells render.
# Turn it off for a pure-writing corpus and drop a few hundred MB.
#
# Fonts: nothing here wraps fontconfig.  Quarto's Typst template asks for
# Libertinus, which Typst embeds, and TeX Live carries its own fonts.  Custom
# font families are the consumer's job — `fonts.packages` on NixOS, or a
# FONTCONFIG_FILE of their own.
{
  lib,
  quarto,
  typst,
  texlive,
  python3,
  symlinkJoin,
  writeShellScriptBin,
  engine ? "typst",
  texliveScheme ? "medium",
  extraTexlivePackages ? [ ],
  notebook ? true,
  # `jupyter-core` (hyphenated) is the current nixpkgs name — `jupyter_core`
  # was renamed and now errors at eval time.
  notebookPackages ? ps: with ps; [
    jupyter-core
    ipykernel
    numpy
    matplotlib
    pandas
  ],
  extraTools ? [ ],
}:

assert lib.elem engine [ "typst" "latex" "both" ];

let
  wantTypst = lib.elem engine [ "typst" "both" ];
  wantLatex = lib.elem engine [ "latex" "both" ];

  # A combined TeX Live tree.  `scheme-*` names are top-level texlive attrs, so
  # they are passed through by name: `inherit` cannot do dynamic attribute
  # names.
  texlive' =
    if wantLatex then
      texlive.combine (
        {
          "scheme-${texliveScheme}" = texlive."scheme-${texliveScheme}";
        }
        # quarto drives latexmk when it is present; without it, it falls back to
        # invoking the engine directly and skips the bibtex/biber re-runs.
        // lib.genAttrs ([ "latexmk" ] ++ extraTexlivePackages) (n: texlive.${n})
      )
    else
      null;

  notebookPython = if notebook then python3.withPackages notebookPackages else null;

  # A human-readable toolchain report.  Also the body of the flake's
  # `apps.doctor`, so `nix run .#doctor` works without entering a dev shell.
  #
  # Each probe tolerates failure: a missing engine is a finding, not an error.
  # Output is captured before being truncated to one line so `pipefail` cannot
  # turn a short read into a SIGPIPE death.
  doctor = writeShellScriptBin "paper-toolchain-doctor" ''
    set -uo pipefail

    probe() {
      local label="$1"; shift
      local out
      if ! command -v "$1" >/dev/null 2>&1; then
        printf '  missing  %s\n' "$label"
        return 0
      fi
      out="$("$@" 2>&1 || true)"
      out="''${out%%$'\n'*}"
      printf '  ok       %-14s %s\n' "$label" "''${out:-present}"
    }

    echo "paper-handler toolchain (engine: ${engine})"
    probe quarto    quarto --version
    probe pandoc    pandoc --version
    probe typst     typst --version
    probe pdflatex  pdflatex --version
    probe lualatex  lualatex --version
    probe latexmk   latexmk --version
    probe jupyter   jupyter --version
    probe python    python --version

    ${lib.optionalString (!wantTypst) ''
      echo
      echo "note: typst is absent by design (engine = ${engine})"
    ''}
    ${lib.optionalString (!notebook) ''
      echo "note: no Jupyter kernel is bundled (notebook = false)"
    ''}

    if ! command -v quarto >/dev/null 2>&1; then
      echo "error: quarto is not on PATH" >&2
      exit 1
    fi
  '';
in
symlinkJoin {
  name = "paper-toolchain-${engine}";
  paths =
    [
      quarto
      doctor
    ]
    ++ lib.optional wantTypst typst
    ++ lib.optional wantLatex texlive'
    ++ lib.optional notebook notebookPython
    ++ extraTools;

  passthru = {
    inherit engine wantTypst wantLatex notebook;
    quartoPackage = quarto;
    texlivePackage = texlive';
    notebookPythonPackage = notebookPython;
  };

  meta = {
    description = "Quarto + Typst/LaTeX toolchain for paper-handler";
    longDescription = ''
      Bundles the `quarto` CLI (with its Pandoc and Typst), an optional TeX Live
      combined scheme, and an optional Jupyter kernel for executable Python
      cells.  Meant to be put on PATH as a unit so `quarto render` is hermetic.
    '';
    mainProgram = "paper-toolchain-doctor";
  };
}
