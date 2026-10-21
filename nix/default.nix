# nix/default.nix — the paper-handler CLI package
#
# The dependency set is not written here: pyproject.toml + uv.lock are the
# source, and flake.nix derives both the package venv and the dev shell from
# them via uv2nix.  `appDeps` is `workspace.deps.optionals`, i.e. every runtime
# dependency plus the opt-in `pdf` extra — but *not* the `dev` group, which
# would drag pytest and ruff into the shipped closure.
#
# `mkApplication` wraps the venv, hiding the interpreter and activation scripts
# while exposing the console entry points from pyproject.toml.

{
  pkgs,
  python,
  pythonSet,
  pyproject-nix,
  appDeps,
}:

let
  inherit (pkgs.callPackages pyproject-nix.build.util { python3 = python; })
    mkApplication;
in
(mkApplication {
  venv = pythonSet.mkVirtualEnv "paper-handler-env" appDeps;
  package = pythonSet."paper-handler";
}).overrideAttrs (old: {
  # `mkApplication` only inherits meta from the Python package, and
  # pyproject.nix does not infer a mainProgram from `[project.scripts]`.
  meta = (old.meta or { }) // {
    mainProgram = "paper-handler";
    description = "Scaffold, render and manage academic papers with Quarto + Typst/LaTeX (CLI + MCP server)";
    license = pkgs.lib.licenses.mit;
  };
})
