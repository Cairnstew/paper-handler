# justfile — https://github.com/casey/just
#
# Everything that can run without the render toolchain uses `.#bootstrap`
# (python + uv only); anything that renders uses `.#default`.

default: test

# Run the MCP registry + JSON-RPC/stdio tests
mcp-test:
	nix develop .#bootstrap -c uv run pytest tests/test_mcp.py tests/test_mcp_research.py tests/test_documents.py -q

# Run the researcher handoff import tests
research-test:
	nix develop .#bootstrap -c uv run pytest tests/test_research.py tests/test_mcp_research.py -q

# Run the pytest suite
test:
	nix develop .#bootstrap -c uv run pytest -q

# Run the suite verbosely
test-verbose:
	nix develop .#bootstrap -c uv run pytest -v

# Lint with ruff
lint:
	nix develop .#bootstrap -c uv run ruff check .

# Apply ruff's autofixes
fix:
	nix develop .#bootstrap -c uv run ruff check --fix .

# Render the bundled example paper with the real toolchain
render-example:
	nix develop -c paper-handler render papers/example

# List the corpus
list:
	nix develop -c paper-handler list

# Full flake check: pytest (in the sandbox), both module evals, real Typst render
check:
	nix flake check

# Build the CLI package
build:
	nix build .#paper-handler

# Print the toolchain report
doctor:
	nix run .#doctor

# Regenerate both lock files from a fresh clone
bootstrap:
	nix develop .#bootstrap -c uv lock
	nix develop .#bootstrap -c uv sync --all-extras --all-groups
