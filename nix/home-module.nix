# nix/home-module.nix — Home Manager module for paper-handler
#
# The per-user counterpart of nix/module.nix.  Import it from the flake:
#
#   inputs.paper-handler.url = "github:Cairnstew/paper-handler";
#
#   imports = [ inputs.paper-handler.homeManagerModules.default ];
#   my.programs.paper-handler.enable = true;
#
# Compared with the NixOS module it is deliberately thinner: no corpus
# directory is created (your papers live wherever you keep them, and a corpus's
# own `paper-handler.toml` already says where) and there is no render timer
# (a systemd user unit is a poor fit for a laptop).  What it does provide is
# the CLI plus toolchain on PATH and a user-level config written to
# `$XDG_CONFIG_HOME/paper-handler/config.toml` — the layer *above* /etc, so a
# corpus still overrides it.
#
# It deliberately does NOT set PAPER_HANDLER_ENGINE: that variable outranks
# every config file, so setting it here would silently pin every corpus to one
# engine.

{
  config,
  lib,
  pkgs,
  paperHandlerPackage ? null,
  ...
}:

let
  cfg = config.my.programs.paper-handler;

  toolchain = pkgs.callPackage ./toolchain.nix {
    engine = cfg.engine;
    inherit (cfg)
      texliveScheme
      extraTexlivePackages
      notebook
      extraTools
      ;
  };

  # Same hand-rolled flat TOML encoder as the NixOS module — kept in sync by
  # eye; see nix/module.nix for why it is not `pkgs.formats`.
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

  package =
    if cfg.package != null then
      cfg.package
    else if paperHandlerPackage != null then
      paperHandlerPackage
    else
      pkgs.paper-handler or null;
in
{
  options.my.programs.paper-handler = {
    enable = lib.mkEnableOption "paper-handler, the Quarto/Typst paper toolchain (CLI + MCP server, user install)";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = null;
      defaultText = lib.literalMD "the flake-injected package, else `pkgs.paper-handler`";
      description = "The `paper-handler` CLI.  Leave null for the flake-injected default.";
    };

    toolchainPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = null;
      defaultText = lib.literalMD "built from nix/toolchain.nix using the options below";
      description = "Override the render toolchain; when set, the toolchain options below are ignored.";
    };

    engine = lib.mkOption {
      type = lib.types.enum [
        "typst"
        "latex"
        "both"
      ];
      default = "typst";
      description = "Which PDF engine the toolchain ships, and the `engine` written to the user config.";
    };

    texliveScheme = lib.mkOption {
      type = lib.types.str;
      default = "medium";
      description = "TeX Live scheme when the engine is `latex` or `both`.";
    };

    extraTexlivePackages = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Extra TeX Live package attribute names to add.";
    };

    notebook = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Bundle a Jupyter kernel so executable ```python cells render.";
    };

    extraTools = lib.mkOption {
      type = lib.types.listOf lib.types.package;
      default = [ ];
      description = "Extra packages to add to the toolchain.";
    };

    papersDir = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Default corpus directory for this user.  Leave null (the default) so
        the CLI keeps using each corpus's own `papers_dir`, falling back to a
        `papers/` directory beside the working directory.  Set it only when you
        want one corpus shared from a fixed location.
      '';
    };

    templatesDir = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Optional shared templates directory (`templates_dir` in the user config).";
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
      description = ''
        Additional keys written to the user config.  Keys the CLI does not know
        are ignored.  `engine`, `papers_dir` and `templates_dir` are set by the
        dedicated options above and take precedence.
      '';
    };
  };

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
        assertion = cfg.papersDir == null || lib.hasPrefix "/" (lib.removePrefix "~/" cfg.papersDir);
        message = "my.programs.paper-handler.papersDir must be absolute (or start with ~/), since the config file cannot rely on the working directory";
      }
    ];

    home.packages = [ toolchain ] ++ lib.optional (package != null) package;

    xdg.configFile."paper-handler/config.toml".text = configText;
  };
}
