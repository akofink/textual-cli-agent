# Developing

This project uses uv for environment management. Dev dependencies and pre-commit hooks are provided for maintaining high code quality.

## Setup

```bash
uv sync --extra dev
pre-commit install  # Install via homebrew if uv version doesn't work
```

## Code Quality

This project maintains high code quality through:

- **Pre-commit hooks**: Automatic formatting and linting on commit
- **Type checking**: Full mypy coverage with strict type checking
- **Test coverage**: 58% coverage with defensive error handling tests
- **Formatting**: Consistent code style with Ruff (formatter enabled)

## Running checks

```bash
# Linting and formatting
uv run ruff check .
uv run ruff format --check .
uv run ruff format --check .

# Type checking
uv run mypy .

# Testing with coverage
uv run pytest
uv run coverage report --show-missing

# Run all pre-commit hooks
uv run pre-commit run --all-files
```

## Test Coverage

The project maintains **58% test coverage** with comprehensive error handling tests:

- Provider error handling (API failures, stream errors, malformed responses)
- Engine error handling (timeouts, tool execution errors, validation)
- UI error handling (rendering errors, input failures, query errors)
- MCP client error handling (connection failures, tool execution errors)

Coverage threshold is set to 55% in `pyproject.toml`.

## Tips

- Use `--prompt-stdin` to preload the UI after streaming the first response from stdin.
- Use `--non-interactive` to run a single streamed response without launching the Textual UI.
- MCP stdio processes are managed by the MCP SDK; pass your server command via `--mcp-stdio`.
