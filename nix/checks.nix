# nix/checks.nix — `nix flake check`
#
# Seven checks, cheapest first:
#
#   pytest            the Python suite (also gated into the package build)
#   module-nixos      full NixOS eval of nix/module.nix against a container-ish
#                     system, plus assertions on the rendered config
#   module-home       full Home Manager eval of nix/home-module.nix
#   module-opencode   eval of the one-import opencode registration
#   mcp-protocol      drive the packaged stdio server with real JSON-RPC
#   research-handoff  import a real researcher handoff, lint and render it
#   render-smoke      actually `paper-handler new` + `render` a paper with the
#                     real Quarto/Typst toolchain.  The only end-to-end proof.
#
# The module checks are eval-only: `lib.nixosSystem` is forced here, and any
# assertion written in NixOS's `assertions` list would fail the eval.  On top
# of that we assert a handful of rendered values so a silent regression in the
# TOML encoder or the option wiring is caught rather than shipped.
{
  lib,
  pkgs,
  # The nixpkgs *flake*, not just `pkgs.lib`: `lib.nixosSystem` only exists on
  # the flake's extended lib, and `pkgs.lib` does not carry it.
  nixpkgs,
  # The flake's *wrapped* modules (they inject the CLI as a module argument),
  # not the bare files — the check should exercise exactly what a consumer
  # imports.
  homeManager,
  nixosModule,
  homeModule,
  opencodeModule,
  paperHandler,
  mcpServer,
  toolchain,
}:

let
  # A host with just enough configuration for `nixosSystem` to evaluate.  A
  # container avoids filesystem, bootloader and hardware declarations.
  minimalHost =
    { lib, ... }:
    {
      boot.isContainer = true;
      system.stateVersion = lib.trivial.release;
    };

  #: A real bundle produced by `researcher-python handoff`; importing it is
  #: the cross-repo contract test.
  handoffFixture = ../tests/fixtures/research-handoff;

  nixosConfig =
    (nixpkgs.lib.nixosSystem {
      inherit (pkgs.stdenv.hostPlatform) system;
      modules = [
        nixosModule
        minimalHost
        {
          my.programs.paper-handler = {
            enable = true;
            render.enable = true;
            users = [ "alice" ];
            extraConfig = { status = "draft"; };
          };
        }
      ];
    }).config;

  etcText = nixosConfig.environment.etc."paper-handler/config.toml".text;

  homeConfig =
    (homeManager.lib.homeManagerConfiguration {
      pkgs = pkgs;
      modules = [
        homeModule
        {
          home.username = "alice";
          home.homeDirectory = "/home/alice";
          home.stateVersion = lib.trivial.release;
          my.programs.paper-handler = {
            enable = true;
            papersDir = "/home/alice/papers";
          };
        }
      ];
    }).config;

  homeText = homeConfig.xdg.configFile."paper-handler/config.toml".text;

  # A minimal stand-in for nixos-config's opencode module: the check only needs
  # the option to exist so the entries can be asserted.
  opencodeStub = { lib, ... }: {
    options.my.programs.opencode.mcp = lib.mkOption {
      type = lib.types.attrsOf lib.types.anything;
      default = { };
    };
  };

  opencodeConfig =
    (homeManager.lib.homeManagerConfiguration {
      pkgs = pkgs;
      modules = [
        opencodeStub
        opencodeModule
        {
          home.username = "alice";
          home.homeDirectory = "/home/alice";
          home.stateVersion = lib.trivial.release;
          my.programs.paper-handler-opencode = {
            enable = true;
            package = paperHandler;
            papersDir = "/home/alice/papers";
            researcher.package = pkgs.hello;
            researcher.home = "/home/alice/.local/share/researcher-python";
          };
        }
      ];
    }).config;

  mcpEntries = opencodeConfig.my.programs.opencode.mcp;

  # `assert cond;` compiles to an eval-time failure with no message, so every
  # check goes through `lib.assertMsg` to keep the failure readable.
  expect = cond: message: lib.assertMsg cond "paper-handler checks: ${message}";

  # `mkApplication` renames the wrapped venv, so match on a substring rather
  # than a prefix: "paper-toolchain" must not match "paper-handler-…".
  hasPackage = fragment: packages: lib.any (p: lib.hasInfix fragment (p.name or "")) packages;
in
{
  # The suite runs as the package's installCheckPhase, so building the package
  # at all is the pytest check.  Naming it here makes it visible in
  # `nix flake check` output rather than hidden inside `packages.default`.
  pytest = paperHandler;

  module-nixos =
    assert expect (lib.hasInfix ''engine = "typst"'' etcText) "NixOS config did not set engine";
    assert expect (lib.hasInfix ''papers_dir = "/var/lib/paper-handler/papers"'' etcText)
      "NixOS config did not set papers_dir";
    assert expect (lib.hasInfix ''status = "draft"'' etcText) "NixOS extraConfig was not merged";
    assert expect (builtins.length (lib.splitString "\n" etcText) > 3) "NixOS config is suspiciously short";
    assert expect (nixosConfig.systemd.services ? "paper-handler-render") "render service missing";
    assert expect (nixosConfig.systemd.timers ? "paper-handler-render") "render timer missing";
    assert expect (nixosConfig.systemd.timers."paper-handler-render".timerConfig.OnCalendar == "*-*-* 03:00:00")
      "render timer OnCalendar not wired";
    assert expect (builtins.elem "alice" nixosConfig.users.groups."paper-handler".members)
      "paper-handler group membership not applied";
    assert expect (
      lib.any (rule: lib.hasPrefix "d /var/lib/paper-handler/papers 2775" rule) nixosConfig.systemd.tmpfiles.rules
    ) "corpus tmpfiles rule missing";
    assert expect (hasPackage "paper-toolchain" nixosConfig.environment.systemPackages)
      "toolchain not on systemPackages";
    assert expect (hasPackage "paper-handler" nixosConfig.environment.systemPackages)
      "CLI not on systemPackages";
    pkgs.runCommand "paper-handler-module-nixos" { } ''
      cat > $out <<'EOF'
      my.programs.paper-handler evaluated:
        engine/papers_dir/extraConfig rendered to /etc
        paper-handler-render.{service,timer} present
        group + tmpfiles rule present
        CLI and toolchain on systemPackages
      EOF
    '';

  module-home =
    assert expect (lib.hasInfix ''engine = "typst"'' homeText) "HM config did not set engine";
    assert expect (lib.hasInfix ''papers_dir = "/home/alice/papers"'' homeText)
      "HM papers_dir not rendered";
    assert expect (hasPackage "paper-toolchain" homeConfig.home.packages) "toolchain not in home.packages";
    assert expect (hasPackage "paper-handler" homeConfig.home.packages) "CLI not in home.packages";
    # PAPER_HANDLER_ENGINE would outrank every corpus config, so the module
    # must not export it.
    assert expect (!(homeConfig.home.sessionVariables ? "PAPER_HANDLER_ENGINE"))
      "HM module must not export PAPER_HANDLER_ENGINE";
    pkgs.runCommand "paper-handler-module-home" { } ''
      cat > $out <<'EOF'
      my.programs.paper-handler (Home Manager) evaluated:
        engine/papers_dir rendered to xdg.configFile
        CLI and toolchain in home.packages
        PAPER_HANDLER_ENGINE deliberately not exported
      EOF
    '';

  module-opencode =
    assert expect (mcpEntries ? "paper-handler") "paper-handler MCP entry missing";
    assert expect (
      mcpEntries."paper-handler".command == [ "${paperHandler}/bin/paper-handler-mcp" ]
    ) "paper-handler MCP command wrong";
    assert expect (mcpEntries."paper-handler".timeout == 120000) "paper-handler MCP timeout wrong";
    assert expect (
      mcpEntries."paper-handler".environment.PAPER_HANDLER_PAPERS_DIR == "/home/alice/papers"
    ) "paper-handler MCP papersDir not exported";
    assert expect (opencodeConfig.my.programs.paper-handler.enable) "package module was not enabled";
    assert expect (mcpEntries ? "researcher") "researcher MCP entry missing";
    assert expect (
      mcpEntries."researcher".command == [ "${pkgs.hello}/bin/researcher-python-mcp" ]
    ) "researcher MCP command wrong";
    assert expect (mcpEntries."researcher".timeout == 120000) "researcher MCP timeout wrong";
    pkgs.runCommand "paper-handler-module-opencode" { } ''
      cat > $out <<'EOF'
      my.programs.paper-handler-opencode evaluated:
        paper-handler and researcher MCP entries
        commands point at the package binaries
        timeout 120000 and papersDir exported
        imported home-module enabled the CLI/toolchain
      EOF
    '';

  # The packaged server, driven the way a client drives it: newline-delimited
  # JSON-RPC on stdin, and nothing but JSON-RPC on stdout.
  mcp-protocol =
    pkgs.runCommand "paper-handler-mcp-protocol"
      {
        # The mcp-server output contains both entry points (paper-handler and
        # paper-handler-mcp), so this exercises exactly what consumers depend on.
        nativeBuildInputs = [ mcpServer ];
      }
      ''
        export HOME="$TMPDIR"
        mkdir -p "$TMPDIR/corpus"
        cd "$TMPDIR/corpus"

        paper-handler init . --engine typst >/dev/null
        export PAPER_HANDLER_CONFIG="$TMPDIR/corpus/paper-handler.toml"
        paper-handler new sample --title "MCP Sample" >/dev/null

        printf '%s\n' \
          '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}' \
          '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
          '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"paper_context","arguments":{"name":"sample"}}}' \
          '{"jsonrpc":"2.0","id":4,"method":"resources/read","params":{"uri":"paper://style-guide"}}' \
          | paper-handler-mcp > responses.jsonl

        test "$(wc -l < responses.jsonl)" -eq 4
        grep -q '"serverInfo"' responses.jsonl
        grep -q '"paper_context"' responses.jsonl
        grep -q 'sections' responses.jsonl
        grep -q 'Academic writing style' responses.jsonl

        # stdout is the protocol stream: every line must be a JSON-RPC object.
        while IFS= read -r line; do
          case "$line" in
            '{"jsonrpc":"2.0"'*) ;;
            *)
              echo "non-JSON-RPC line on stdout: $line" >&2
              exit 1
              ;;
          esac
        done < responses.jsonl

        cat > $out <<'EOF'
        paper-handler-mcp spoke JSON-RPC over stdio:
          initialize, tools/list, tools/call paper_context, resources/read
          stdout contained only JSON-RPC objects
        EOF
      '';

  # Import a real researcher handoff, cite a key from each bibliography, and
  # render.  No network: the fixture is committed and the toolchain is local.
  research-handoff =
    pkgs.runCommand "paper-handler-research-handoff"
      {
        nativeBuildInputs = [
          paperHandler
          toolchain
        ];
      }
      ''
        export HOME="$TMPDIR"
        mkdir -p "$TMPDIR/corpus"
        cd "$TMPDIR/corpus"

        paper-handler init . --engine typst >/dev/null
        export PAPER_HANDLER_CONFIG="$TMPDIR/corpus/paper-handler.toml"

        paper-handler research import ${handoffFixture} --paper sample --title "Research Fixture"
        test -f papers/sample/research/references.bib
        test -f papers/sample/research/citation-map.json
        grep -q "research/references.bib" papers/sample/index.qmd

        # One citation from each bibliography: the manual template file and the
        # generated handoff file.
        printf '\n\nCite [@doe2024] and [@smith2020attention].\n' >> papers/sample/index.qmd
        paper-handler lint papers/sample

        # The PRISMA appendix is an include, so rendering proves Quarto resolves
        # research/prisma.md as well as the two bibliographies.
        paper-handler research prisma papers/sample
        grep -q "include research/prisma.md" papers/sample/index.qmd

        paper-handler render papers/sample
        test -f papers/sample/index.pdf

        echo "imported the handoff, resolved both bibliographies, rendered $(wc -c < papers/sample/index.pdf) bytes" > $out
      '';

  # The only check that actually renders.  Needs no network: templates ship
  # inside the package, and Quarto bundles its own Typst.
  render-smoke =
    pkgs.runCommand "paper-handler-render-smoke"
      {
        nativeBuildInputs = [
          paperHandler
          toolchain
        ];
      }
      ''
        export HOME="$TMPDIR"
        mkdir -p "$TMPDIR/corpus"
        cd "$TMPDIR/corpus"

        paper-handler init . --engine typst
        # Pin config discovery to this corpus's own file so a stray
        # /etc/paper-handler/config.toml or ~/.config on the build host cannot
        # redirect the render (darwin builds have no sandbox).
        export PAPER_HANDLER_CONFIG="$TMPDIR/corpus/paper-handler.toml"

        paper-handler new smoke-test --title "Render Smoke Test"
        test -f papers/smoke-test/index.qmd
        test -f papers/smoke-test/references.bib

        paper-handler doctor --json
        paper-handler render papers/smoke-test

        test -f papers/smoke-test/index.pdf
        # `wc -c` rather than `stat -c%s`: portable to darwin.
        echo "rendered $(wc -c < papers/smoke-test/index.pdf) bytes" > $out
      '';
}
