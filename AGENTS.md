# Repository Guidelines

This guide orients new contributors to the Textual-based CLI agent. It highlights repository layout, everyday workflows, and collaboration expectations. Consult `Roadmap.md` before starting work so efforts align with current priorities.

## Project Structure & Module Organization
- `textual_cli_agent/` houses runtime code; `cli.py` wires the CLI, `engine.py` coordinates provider calls, and `context_manager.py` keeps session state.
- Provider adapters live in `textual_cli_agent/providers/`, MCP transport logic in `textual_cli_agent/mcp/`, and UI widgets/themes in `textual_cli_agent/ui/`.
- Sample tool registrations are in `textual_cli_agent/examples/tools_example.py`; mirror that pattern when exposing new tools.
- Tests mirror the package in `tests/`, with fixtures in `tests/conftest.py`. Repository configuration lives in `pyproject.toml` and `DEVELOPING.md`.

## Build, Test, and Development Commands
- `uv sync --extra dev` installs runtime and development dependencies.
- `uv run textual-cli-agent --help` verifies the CLI entry point after changes.
- `uv run pytest` executes the Pytest suite (include Textual UI actor tests for widgets and panels); pair with `uv run coverage report --show-missing` for visibility.
- `uv run ruff check .` and `uv run ruff format --check .` enforce linting and formatting.
- `uv run mypy .` runs strict type checking; keep new modules clean.
- `uv run pre-commit run --all-files` is the final gate; hooks must pass before submitting a PR. Never bypass hooks—they mirror CI requirements.

## Coding Style & Naming Conventions
Use 4-space indentation, type annotations, and Ruff-compatible formatting (Black-like layout, double quotes). Prefer snake_case for functions and variables, PascalCase for classes, and CLI command names that mirror module filenames. Keep log messages actionable and include provider or tool names when relevant.

## Testing Guidelines
Pytest drives testing; add `test_*.py` modules under `tests/` mirroring the package path. Target ≥55% coverage (threshold in `pyproject.toml`) and capture regressions for providers, MCP transports, and UI error handling. For new tools or widgets, include async scenarios with `pytest.mark.asyncio` and exercise failure paths.

## Commit & Pull Request Guidelines
Write imperative, descriptive commit subjects; conventional prefixes (`feat:`, `fix:`) are welcome but optional. Keep commits scoped to one logical change and ensure hooks pass before pushing. Pull requests should describe behavior changes, list commands run (tests, lint, type-check), link related issues, and include screenshots or terminal captures for UI-facing updates. Update README or DEVELOPING notes when you add new provider flags, tools, or configuration switches.

## Agent-Specific Tips
Document new providers or transports in `README.md` and surface configuration flags through `cli.py`. Expose tools via the decorator in `textual_cli_agent/tools.py`, update `textual_cli_agent/examples/tools_example.py`, and follow the defensive patterns in `error_handler.py` for network or I/O calls.
