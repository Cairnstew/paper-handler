# nix/devshell.nix — development shells.
#
#   nix develop             default: editable venv + full render toolchain
#   nix develop .#bootstrap python + uv only, and deliberately independent of
#                           `workspace`, so it still evaluates before the first
#                           `uv lock` exists
#
# Returned as a plain attrset; flake.nix strips `callPackage`'s injected
# `override`/`__functionArgs` attrs before exposing it as `devShells`.
{
  pkgs,
  python,
  # The *editable* Python set, not the packaged one: `mkVirtualEnv` over it
  # installs the project itself as an editable pointing at `$REPO_ROOT`, so
  # edits to src/ are picked up without reinstalling.
  editablePythonSet,
  workspace,
  toolchain,
}:

let
  # The editable venv: every dependency from pyproject.toml + uv.lock, plus the
  # project itself editable.
  venv = editablePythonSet.mkVirtualEnv "paper-handler-dev-env" workspace.deps.all;
in
{
  default = pkgs.mkShell {
    packages = [
      venv
      toolchain
      pkgs.uv
      pkgs.git
      pkgs.just
    ];

    env = {
      UV_NO_SYNC = "1";
      UV_PYTHON = "${python.interpreter}";
      UV_PYTHON_DOWNLOADS = "never";
      # Deliberately no PAPER_HANDLER_ENGINE: that variable outranks every
      # config file, so exporting it here would pin every corpus to the
      # toolchain's engine and silently defeat per-corpus `paper-handler.toml`.
    };

    shellHook = ''
      # The editable overlay resolves `$REPO_ROOT`; a stray PYTHONPATH from the
      # caller would shadow it (and any caller-set PAPER_HANDLER_* would
      # silently re-point the corpus).
      unset PYTHONPATH
      export REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
      {
        echo "paper-handler dev shell (uv2nix)"
        echo "  toolchain: ${toolchain.name}"
        python -c 'import paper_handler, click, yaml; print("  deps ok")'
        command -v quarto >/dev/null && echo "  $(quarto --version | head -n1)"
      } >&2
    '';
  };

  # Pre-lock shell.  Touches nothing from `workspace`: no uv.lock, no overlay,
  # no mkVirtualEnv — so it works on a fresh clone, where the rest of the flake
  # cannot evaluate yet.  Run `uv lock` from here.
  bootstrap = pkgs.mkShell {
    packages = [
      python
      pkgs.uv
    ];

    shellHook = ''
      echo "paper-handler bootstrap shell (run: uv lock)" >&2
    '';
  };
}
