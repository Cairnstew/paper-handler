# paper-handler — Quarto + Typst/LaTeX paper generation
{
  description = "paper-handler — Nix module + Python CLI for academic paper generation (Quarto, Typst/LaTeX)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Only used by `checks.module-home`: a full Home Manager eval is the only
    # real way to know the HM module still works.
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      uv2nix,
      pyproject-nix,
      pyproject-build-systems,
      home-manager,
      ...
    }:
    let
      inherit (nixpkgs) lib;
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
        "x86_64-darwin"
      ];
      forAllSystems = lib.genAttrs supportedSystems;

      # `pyproject.toml` + `uv.lock` are the only dependency source.  Everything
      # below derives from this workspace — there is deliberately no dependency
      # list in this file.  `workspace` is a `let` binding, so it is only forced
      # by outputs that actually need it; the `bootstrap` shell in
      # nix/devshell.nix therefore still evaluates before the first `uv lock`.
      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };

      editableOverlay = workspace.mkEditablePyprojectOverlay {
        root = "$REPO_ROOT";
      };

      # Runtime extras (pdf) are opt-in in `pyproject.toml`; the Nix package
      # ships all of them so `nix build` gives a fully featured CLI.
      # `deps.optionals` is the optional/default groups; `deps.all` would also
      # pull in the `dev` group (pytest, ruff) into the shipped binary closure.
      appDeps = workspace.deps.optionals;

      pythonSets = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python3;

          baseSet = pkgs.callPackage pyproject-nix.build.packages {
            inherit python;
          };

          basePythonSet = baseSet.overrideScope (
            lib.composeManyExtensions [
              pyproject-build-systems.overlays.wheel
              overlay
            ]
          );

          # Run the offline suite inside the sandbox.  pyproject.nix/nixpkgs
          # rename `checkPhase` to `installCheckPhase` for Python packages, so
          # an `overrideAttrs { checkPhase = ...; }` would be silently ignored.
          #
          # The check environment is a venv built from the *dependency closure*
          # of `workspace.deps.all` rather than a hand-maintained list;
          # `query.deps` excludes the queried package itself, so no cycle.
          # PYTHONPATH puts the source tree first so tests exercise the
          # checkout.
          testOverlay =
            final: prev:
            let
              checkEnv = final.mkVirtualEnv "paper-handler-check-env" (
                pyproject-nix.build.lib.query.deps { } final workspace.deps.all
              );
            in
            {
              paper-handler = prev.paper-handler.overrideAttrs (old: {
                doInstallCheck = true;
                installCheckPhase = ''
                  runHook preInstallCheck
                  export PYTHONPATH="$PWD''${PYTHONPATH:+:$PYTHONPATH}"
                  ${checkEnv}/bin/python -m pytest tests/ -q
                  runHook postInstallCheck
                '';
              });
            };

          pythonSet = basePythonSet.overrideScope testOverlay;
          editablePythonSet = basePythonSet.overrideScope editableOverlay;
        in
        {
          inherit
            pythonSet
            editablePythonSet
            python
            pkgs
            ;
        }
      );
    in
    {
      # ── Packages ──────────────────────────────────────────────────────────
      # `nix build .#paper-handler`, `nix build .#toolchain`, `nix build`.
      packages = forAllSystems (
        system:
        let
          p = pythonSets.${system};
          cli = p.pkgs.callPackage ./nix/default.nix {
            inherit (p) python pythonSet;
            inherit pyproject-nix appDeps;
          };
          toolchain = p.pkgs.callPackage ./nix/toolchain.nix {
            python3 = p.python;
          };
        in
        {
          default = cli;
          paper-handler = cli;
          # Same binaries, distinct output so consumers can depend on the
          # server without implying they want the CLI's mainProgram.
          mcp-server = cli.overrideAttrs (old: {
            meta = (old.meta or { }) // {
              mainProgram = "paper-handler-mcp";
              description = "MCP (stdio) server for paper-handler";
            };
          });
          inherit toolchain;
        }
      );

      # ── Overlays ─────────────────────────────────────────────────────────
      # `pkgs.paper-handler` and `pkgs.paper-toolchain` on a consumer's package
      # set.  Both modules below accept `package`/`toolchain` options, so this
      # is only needed by consumers who want to reach them directly.
      overlays.default = final: prev: {
        paper-handler = pythonSets.${prev.stdenv.hostPlatform.system}.pythonSet."paper-handler";
        paper-toolchain = final.callPackage ./nix/toolchain.nix { };
      };

      # ── Modules ──────────────────────────────────────────────────────────
      # Both declare options but never apply themselves: a host has to set
      # `my.programs.paper-handler.enable = true`.  The NixOS half provisions the
      # toolchain system-wide, materialises the corpus directory and optionally
      # runs a render timer; the Home Manager half is the per-user equivalent.
      #
      # The thin wrappers inject the CLI as a module argument, so a consumer
      # does not need the overlay just to get a package.  `paperHandlerPackage`
      # is a thunk that is only forced when `enable = true`, so importing the
      # module on a host that does not use it costs nothing.
      nixosModules.default =
        { pkgs, ... }:
        {
          imports = [ ./nix/module.nix ];
          config._module.args.paperHandlerPackage =
            (self.packages.${pkgs.stdenv.hostPlatform.system} or { }).paper-handler or null;
        };

      homeManagerModules.default =
        { pkgs, ... }:
        {
          imports = [ ./nix/home-module.nix ];
          config._module.args.paperHandlerPackage =
            (self.packages.${pkgs.stdenv.hostPlatform.system} or { }).paper-handler or null;
        };

      # One import for the CLI, the toolchain and the MCP server(s).  It imports
      # the package module itself; `researcher.package` additionally registers
      # researcher-python's server.
      homeManagerModules.opencode =
        { pkgs, ... }:
        {
          imports = [ ./nix/opencode-module.nix ];
          config._module.args.paperHandlerPackage =
            (self.packages.${pkgs.stdenv.hostPlatform.system} or { }).mcp-server or null;
        };

      # ── Checks ───────────────────────────────────────────────────────────
      # `nix flake check` evals both modules against representative configs,
      # runs the pytest suite in the sandbox (as part of building the package),
      # and renders a scaffolded paper with Typst.  The last one is the
      # expensive check — skip everything expensive with `--no-build`.
      checks = forAllSystems (
        system:
        let
          raw = nixpkgs.legacyPackages.${system}.callPackage ./nix/checks.nix {
            inherit nixpkgs;
            homeManager = home-manager;
            nixosModule = self.nixosModules.default;
            homeModule = self.homeManagerModules.default;
            opencodeModule = self.homeManagerModules.opencode;
            toolchain = self.packages.${system}.toolchain;
            paperHandler = self.packages.${system}.paper-handler;
            mcpServer = self.packages.${system}.mcp-server;
          };
        in
        # `callPackage` appends `override`/`overrideDerivation`/`__functionArgs`
        # to the returned attrset; `checks` may only contain derivations.
        lib.filterAttrs (
          n: _: !builtins.elem n [ "override" "overrideDerivation" "__functionArgs" ]
        ) raw
      );

      # ── Apps ─────────────────────────────────────────────────────────────
      # `nix run .#doctor` — verify the toolchain without entering a shell.
      apps = forAllSystems (system: {
        doctor = {
          type = "app";
          program = "${self.packages.${system}.toolchain}/bin/paper-toolchain-doctor";
          meta.description = "Report which paper-handler render tools are on PATH";
        };
        mcp-server = {
          type = "app";
          program = "${self.packages.${system}.mcp-server}/bin/paper-handler-mcp";
          meta.description = "Run the paper-handler MCP server over stdio";
        };
      });

      # ── Dev Shell ────────────────────────────────────────────────────────
      # `nix develop` = editable venv + the full render toolchain.
      # `nix develop .#bootstrap` = python + uv only, and deliberately does not
      # touch `workspace`, so it still evaluates before the first `uv lock`.
      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          p = pythonSets.${system};
          raw = p.pkgs.callPackage ./nix/devshell.nix {
            inherit (p) python pkgs;
            inherit workspace;
            editablePythonSet = p.editablePythonSet;
            toolchain = self.packages.${system}.toolchain;
          };
          # `callPackage` hands extra args through the result; strip them so
          # devShells only contains derivations.
        in
        lib.filterAttrs (
          n: _: !builtins.elem n [ "override" "overrideDerivation" "__functionArgs" ]
        ) raw
      );
    };
}
