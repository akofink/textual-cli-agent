# Developing

This project uses uv for environment management. Dev dependencies and pre-commit hooks are provided.

## Setup

```bash
uv sync --extra dev
pre-commit install
```

## Running checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run black --check .
uv run mypy .
uv run pytest
```

## Tips

- Use `--prompt-stdin` to preload the UI after streaming the first response from stdin.
- Use `--non-interactive` to run a single streamed response without launching the Textual UI.
- MCP stdio processes are managed by the MCP SDK; pass your server command via `--mcp-stdio`.
