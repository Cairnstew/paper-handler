# nix/module.nix — NixOS module for paper-handler
#
# Import from the flake:
#
#   inputs.paper-handler.url = "github:Cairnstew/paper-handler";
#
#   imports = [ inputs.paper-handler.nixosModules.default ];
#   my.programs.paper-handler.enable = true;
#
# What it does when enabled:
#   * puts the `paper-handler` CLI and the render toolchain on PATH
#     system-wide (so `nix run` is unnecessary and every user gets them),
#   * materialises the corpus directory with a setgid group so several users
#     can share one paper tree,
#   * writes /etc/paper-handler/config.toml — the lowest-precedence layer the
#     CLI reads, so a per-corpus `paper-handler.toml` still overrides it,
#   * optionally runs `paper-handler render --all` from a systemd timer.
#
# Nothing here applies itself: the module declares options and, when
# `enable = true`, the config above.  The CLI package defaults to the one the
# flake injects as a module argument (`paperHandlerPackage`); a consumer using
# the overlay instead gets `pkgs.paper-handler` automatically.

{
  config,
  lib,
  pkgs,
  # Injected by the flake wrapper around this file.  Null when the module is
  # vendored/copied without the flake, in which case `pkgs.paper-handler`
  # (overlay) or an explicit `package` is required.
  paperHandlerPackage ? null,
  ...
}:

let
  cfg = config.my.programs.paper-handler;

  # ── Toolchain ─────────────────────────────────────────────────────────────
  # Built from nix/toolchain.nix with the module's own knobs, so a host does
  # not need the overlay just to get a working `quarto`.
  toolchain = pkgs.callPackage ./toolchain.nix {
    engine = cfg.engine;
    inherit (cfg)
      texliveScheme
      extraTexlivePackages
      notebook
      extraTools
      ;
  };

  # ── TOML rendering ────────────────────────────────────────────────────────
  # Hand-rolled rather than `pkgs.formats` (which has no `toml` generator) and
  # deliberately flat: every key the CLI reads is a top-level scalar or a list
  # of strings, and `_apply_layer` ignores unknown keys anyway.
  tomlEscape = s: builtins.replaceStrings [ "\\" ''"'' "\n" "\t" ] [ "\\\\" ''\"'' "\\n" "\\t" ] (toString s);

  tomlValue =
    v:
    if builtins.isBool v then
      (if v then "true" else "false")
    else if builtins.isInt v || builtins.isFloat v then
      toString v
    else if builtins.isList v then
      "[${builtins.concatStringsSep ", " (map (e: ''"${tomlEscape e}"'') v)}]"
    else
      ''"${tomlEscape v}"'';

  # Explicit module options win over `extraConfig`, so a consumer cannot
  # accidentally contradict `engine`/`papersDir` in two places.
  configAttrs =
    cfg.extraConfig
    // {
      engine = cfg.engine;
    }
    // lib.optionalAttrs (cfg.papersDir != null) { papers_dir = cfg.papersDir; }
    // lib.optionalAttrs (cfg.templatesDir != null) { templates_dir = cfg.templatesDir; };

  configText =
    let
      names = lib.attrNames configAttrs;
    in
    lib.concatMapStrings (name: "${name} = ${tomlValue configAttrs.${name}}\n") names;

  # ── Packages ──────────────────────────────────────────────────────────────
  package =
    if cfg.package != null then
      cfg.package
    else if paperHandlerPackage != null then
      paperHandlerPackage
    else
      pkgs.paper-handler or null;

  shellPackages = [ toolchain ] ++ lib.optional (package != null) package;
in
{
  # ── Options ───────────────────────────────────────────────────────────────
  options.my.programs.paper-handler = {
    enable = lib.mkEnableOption "paper-handler, the Quarto/Typst paper toolchain (CLI + MCP server)";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = null;
      defaultText = lib.literalMD "the flake-injected package, else `pkgs.paper-handler`";
      description = ''
        The `paper-handler` CLI.  Leave null to use the package the flake
        injects (or `pkgs.paper-handler` when the overlay is imported).
      '';
    };

    toolchainPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = null;
      defaultText = lib.literalMD "built from nix/toolchain.nix using the options below";
      description = ''
        Override the render toolchain (Quarto + engine).  When null it is built
        here from `engine`, `texliveScheme`, `notebook` and friends; when set,
        those toolchain options are ignored.
      '';
    };

    engine = lib.mkOption {
      type = lib.types.enum [
        "typst"
        "latex"
        "both"
      ];
      default = "typst";
      description = ''
        Which PDF engine the toolchain ships.  `typst` (default) is fast and
        small; `latex` adds TeX Live for journal templates with LaTeX classes;
        `both` ships both.  This also seeds `engine` in /etc/paper-handler/config.toml.
      '';
    };

    texliveScheme = lib.mkOption {
      type = lib.types.str;
      default = "medium";
      description = "TeX Live scheme to combine when the engine is `latex` or `both`.";
    };

    extraTexlivePackages = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [
        "apa7"
        "appendix"
      ];
      description = "Extra TeX Live collection/package attribute names to add.";
    };

    notebook = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Bundle a Jupyter kernel so executable ```python cells render.";
    };

    extraTools = lib.mkOption {
      type = lib.types.listOf lib.types.package;
      default = [ ];
      description = "Extra packages to add to the toolchain derivation.";
    };

    papersDir = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = "/var/lib/paper-handler/papers";
      description = ''
        System-wide corpus directory.  Written as `papers_dir` (absolute —
        relative paths in /etc would resolve under /etc) into the system
        config, created with mode 2775 and group `paper-handler` so several
        users can share one tree.  Set to null to leave the directory to the
        CLI's own `papers/` discovery.
      '';
    };

    templatesDir = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Optional shared templates directory (`templates_dir` in the system config).";
    };

    users = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "seanc" ];
      description = "Users granted write access to the shared corpus (members of `paper-handler`).";
    };

    extraConfig = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.oneOf [
          lib.types.str
          lib.types.int
          lib.types.bool
          (lib.types.listOf lib.types.str)
        ]
      );
      default = { };
      example = { status = "draft"; };
      description = ''
        Additional keys written to /etc/paper-handler/config.toml.  Keys the CLI
        does not know are ignored, so this is safe for forward compatibility.
        `engine`, `papers_dir` and `templates_dir` are set by the dedicated
        options above and take precedence over this attrset.
      '';
    };

    render = {
      enable = lib.mkEnableOption "a systemd timer that runs `paper-handler render --all`";

      onCalendar = lib.mkOption {
        type = lib.types.str;
        default = "*-*-* 03:00:00";
        description = "systemd OnCalendar expression for the render timer.";
      };

      user = lib.mkOption {
        type = lib.types.str;
        default = "root";
        description = "User the render service runs as.";
      };

      group = lib.mkOption {
        type = lib.types.str;
        default = "paper-handler";
        description = "Group the render service runs as.";
      };

      extraArgs = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        example = [
          "--engine"
          "latex"
        ];
        description = "Extra arguments appended to `paper-handler render --all`.";
      };
    };
  };

  # ── Config ────────────────────────────────────────────────────────────────
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = package != null;
        message = ''
          my.programs.paper-handler: no CLI package available.  Either import
          paper-handler's overlay (`overlays.default`), or set
          `my.programs.paper-handler.package`.
        '';
      }
      {
        assertion = cfg.papersDir == null || lib.hasPrefix "/" cfg.papersDir;
        message = "my.programs.paper-handler.papersDir must be absolute (it is read from /etc, so a relative path would resolve under /etc)";
      }
      {
        assertion = !cfg.render.enable || cfg.render.onCalendar != "";
        message = "my.programs.paper-handler.render.onCalendar must not be empty when the render timer is enabled";
      }
    ];

    environment.systemPackages = shellPackages;

    # Lowest-precedence config layer.  Written with an absolute papers_dir so
    # `_apply_layer`'s config-file-relative anchoring cannot point it at /etc.
    environment.etc."paper-handler/config.toml".text = configText;

    # Shared corpus: setgid so files created inside inherit the group.
    users.groups.paper-handler.members = cfg.users;
    systemd.tmpfiles.rules = lib.optional (cfg.papersDir != null) (
      "d ${cfg.papersDir} 2775 root paper-handler -"
    );

    systemd.services.paper-handler-render = lib.mkIf cfg.render.enable {
      description = "Render every paper in the paper-handler corpus";
      path = shellPackages;
      serviceConfig = {
        Type = "oneshot";
        User = cfg.render.user;
        Group = cfg.render.group;
      };
      script = ''
        exec paper-handler render --all ${lib.escapeShellArgs cfg.render.extraArgs}
      '';
    };

    systemd.timers.paper-handler-render = lib.mkIf cfg.render.enable {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.render.onCalendar;
        Persistent = true;
        RandomizedDelaySec = "10m";
      };
    };
  };
}
