# Phase 1 Backlog – Experience & Reliability Enhancements

The first roadmap phase focuses on stability, insight, and workspace intelligence. Each epic below lists concrete tasks, owners TBD, and required validation.

## Epic: Streaming Resilience

- [ ] Implement provider-agnostic retry/backoff with jitter for stream interruptions.
- [ ] Surface reconnection status in UI status bar.
- [ ] Add integration tests simulating network failures (pytest + httpx mocking).
- [ ] Update README troubleshooting section with recovery behavior.

## Epic: Session Insights

- [ ] Add Textual side panel summarizing tool calls, token usage, and provider costs.
- [ ] Persist session stats for export (JSON) and clipboard copy.
- [ ] Write Textual `Pilot` UI tests to validate panel toggles and content.
- [ ] Document feature in README usage section.

## Epic: Workspace Intelligence

- [ ] Introduce repo indexer (ripgrep + embeddings placeholder) with caching.
- [ ] Provide new tools: `search_workspace`, `summarize_file`.
- [ ] Cover with unit tests for indexing plus integration tests using sample repo fixtures.
- [ ] Extend AGENTS.md with guidance on index maintenance.

## Epic: Onboarding & Docs Refresh

- [ ] Implement guided first-run checklist explaining providers, tools, MCP.
- [ ] Add “Get Started” section in README linking to tutorial.
- [ ] Record demo GIF or terminal capture for README once other epics land.
- [ ] Ensure Roadmap/Developing/Agents updates accompany each delivery.

## Quality Gates

- All tasks must maintain ≥55% coverage (bump threshold once metrics improve).
- Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`, `uv run pytest --cov=textual_cli_agent`.
- Pre-commit hooks remain mandatory; GitHub Actions CI must be green before merge.
