# nix/opencode-module.nix — register the paper-handler (and optionally the
# researcher-python) MCP servers with opencode.
#
# Import the flake output:
#
#   imports = [ inputs.paper-handler.homeManagerModules.opencode ];
#   my.programs.paper-handler-opencode = {
#     enable = true;
#     configFile = "${config.home.homeDirectory}/papers/paper-handler.toml";
#     researcher.package = inputs.researcher-python.packages.${pkgs.system}.default;
#   };
#
# This module imports the package module, so one import gives you the CLI, the
# render toolchain and both stdio servers. `researcher.package` is optional:
# set it to register `researcher-python-mcp` alongside `paper-handler-mcp`; if
# researcher-python's own Home Manager module is imported instead, leave it
# null and let that module own its entry.
#
# opencode's default MCP startup timeout is 5000 ms, which a cold Nix shell
# easily exceeds; both entries default to 120000 ms.
{
  config,
  lib,
  pkgs,
  # Injected by the flake wrapper around this file.
  paperHandlerPackage ? null,
  ...
}:

let
  cfg = config.my.programs.paper-handler-opencode;
  package =
    if cfg.package != null then
      cfg.package
    else if paperHandlerPackage != null then
      paperHandlerPackage
    else
      pkgs.paper-handler or null;

  paperEnvironment =
    lib.optionalAttrs (cfg.configFile != null) {
      PAPER_HANDLER_CONFIG = cfg.configFile;
    }
    // lib.optionalAttrs (cfg.papersDir != null) {
      PAPER_HANDLER_PAPERS_DIR = cfg.papersDir;
    };

  researcherEnvironment =
    lib.optionalAttrs (cfg.researcher.home != null) {
      RESEARCHER_HOME = cfg.researcher.home;
    }
    // lib.optionalAttrs (cfg.researcher.envFile != null) {
      RESEARCHER_ENV_FILE = cfg.researcher.envFile;
    }
    // lib.optionalAttrs (cfg.researcher.workspace != null) {
      RESEARCHER_WORKSPACE = cfg.researcher.workspace;
    };
in
{
  imports = [ ./home-module.nix ];

  options.my.programs.paper-handler-opencode = {
    enable = lib.mkEnableOption "the paper-handler and optional researcher MCP servers in opencode";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = null;
      defaultText = lib.literalMD "the flake-injected package, else `pkgs.paper-handler`";
      description = "The paper-handler package (provides `paper-handler-mcp`).";
    };

    configFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "/home/you/papers/paper-handler.toml";
      description = ''
        Optional `PAPER_HANDLER_CONFIG` for a globally launched server. The
        server otherwise discovers a corpus from its working directory.
      '';
    };

    papersDir = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "/home/you/papers";
      description = "Optional `PAPER_HANDLER_PAPERS_DIR` (ignored when `configFile` is set).";
    };

    timeout = lib.mkOption {
      type = lib.types.int;
      default = 120000;
      description = "MCP startup timeout in milliseconds (opencode's default is 5000).";
    };

    researcher = {
      package = lib.mkOption {
        type = lib.types.nullOr lib.types.package;
        default = null;
        description = ''
          Optional researcher-python package. When set, register
          `researcher-python-mcp` in the same import. If researcher-python's own
          Home Manager module is imported, leave this null.
        '';
      };

      home = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = "${config.home.homeDirectory}/.local/share/researcher-python";
        description = "Root for named researcher workspaces (`RESEARCHER_HOME`).";
      };

      envFile = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Absolute `.env` path for researcher credentials (never in the Nix store).";
      };

      workspace = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Optional default researcher workspace (`RESEARCHER_WORKSPACE`).";
      };

      timeout = lib.mkOption {
        type = lib.types.int;
        default = 120000;
        description = "MCP startup timeout for the researcher server.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = package != null;
        message = ''
          my.programs.paper-handler-opencode: no paper-handler package.
          Import the overlay or set `package`.
        '';
      }
      {
        assertion = !(cfg.configFile != null && cfg.papersDir != null);
        message = ''
          my.programs.paper-handler-opencode: set `configFile` or `papersDir`,
          not both (the config file already names the corpus).
        '';
      }
      {
        assertion = !(cfg.researcher.envFile != null && lib.hasPrefix "/nix/store/" cfg.researcher.envFile);
        message = ''
          my.programs.paper-handler-opencode.researcher.envFile must not point
          into the Nix store; use a home file or agenix.
        '';
      }
    ];

    # The MCP server needs the CLI package; the package module also puts the
    # render toolchain on PATH. Default it on so one import is self-contained.
    my.programs.paper-handler.enable = lib.mkDefault true;
    my.programs.paper-handler.papersDir = lib.mkDefault cfg.papersDir;

    my.programs.opencode.mcp.paper-handler = lib.mkDefault {
      enabled = true;
      type = "local";
      command = [ "${package}/bin/paper-handler-mcp" ];
      environment = paperEnvironment;
      timeout = cfg.timeout;
    };

    my.programs.opencode.mcp.researcher = lib.mkIf (cfg.researcher.package != null) (
      lib.mkDefault {
        enabled = true;
        type = "local";
        command = [ "${cfg.researcher.package}/bin/researcher-python-mcp" ];
        environment = researcherEnvironment;
        timeout = cfg.researcher.timeout;
      }
    );
  };
}
