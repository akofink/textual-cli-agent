# Roadmap

## Vision

Build the most useful LLM-powered CLI companion—fast, reliable, deeply extensible, and trusted for mission-critical development and operations. We will combine rich Textual interfaces with autonomous orchestration, strong tooling integrations, and uncompromising quality gates to outclass Codex, Claude Code, Atlassian RovoDev CLI, Toad, Gemini CLI, and emerging rivals.

## Guiding Principles

- **Trust beats novelty**: deterministic quality gates (tests, type checks, coverage, pre-commit) gate every merge.
- **Fast feedback**: snappy startup, resilient streaming, actionable errors.
- **User choice**: first-class multi-provider, local + hosted, and hybrid toolchains.
- **Ergonomic power**: advanced tooling without sacrificing keyboard-first simplicity.
- **Documented always**: README/AGENTS/ROADMAP kept current with every iteration.

## Competitive Snapshot

| Feature Area | State Today | Competitor Signals | Gap / Opportunity |
| --- | --- | --- | --- |
| Provider support | OpenAI, Anthropic, Ollama | Claude Code focuses on Anthropic, Gemini CLI on Gemini | Expand to Azure OpenAI, Mistral, Bedrock; seamless provider presets |
| UI/UX | Textual UI + headless mode | Toad excels at multi-pane layout and knowledge widgets | Add multi-pane layouts, command palette actions, AI insights |
| Tooling | Python tools + MCP tools | RovoDev integrates Atlassian stack; Codex/Claude embed repo/exec tasks | Build turnkey Git, issue trackers, cloud CLIs; plugin marketplace |
| Automation | Manual prompt-driven sessions | Competitors offer workflows/macros (Toad) | Add agentic plans, macros, scheduled jobs |
| Collaboration | Export via clipboard/file | Gemini CLI shares to Google docs/workspace | Add session sync, shared transcripts, team workspaces |

## Multi-Phase Roadmap

### Phase 0 — Hardening & Foundations (in flight)
- ✅ Add Ollama provider with detailed error surfacing and clipboard UX.
- ✅ Pre-commit hooks enforce lint, format, type, tests (already active).
- ⬜ Expand documentation (README, AGENTS, DEVELOPING) to cover providers, quality gates, and new roadmap (this cycle).
- ⬜ Enable coverage and test summaries in CI (scriptable via `uv run coverage`).

### Phase 1 — Experience & Reliability Enhancements
Tracked in detail at `tasks/phase1_backlog.md`.
1. **Streaming resilience**
   - Implement auto-reconnect streams, retry backoff per provider.
   - Tests: async integration tests mocking network flaps.
2. **Session insights**
   - Side panel summarizing conversation state, tool usage, costs.
   - UI tested via Textual `Pilot`/`Screenshotter`.
3. **Workspace intelligence**
   - Built-in repo indexer (ripgrep + embeddings) for recall, referencing Claude Code's project context.
   - Unit tests for indexer, integration tests with sample repos.
4. **Onboarding & docs**
   - Guided first-run flow, README quick-start paths for each provider.

### Phase 2 — Tooling & Automation
1. **Native workflow macros**
   - Reusable scripts (YAML/TOML) describing multi-step tasks.
   - Execution sandbox with undo, logging.
2. **Git & issue triage toolkit**
   - Commands: `git plan`, PR review, issue summarizer.
   - Ensure compliance with linters/tests.
3. **Environment adapters**
   - Azure OpenAI, AWS Bedrock, Google Vertex/Gemini toggles.
   - Integration tests hitting mocked APIs; type-safe configs.
4. **Structured logging & telemetry**
   - JSON logs, opt-in analytics, runtime health view.
5. **Documentation automation**
   - CLI command to refresh feature docs, changelog snippets.

### Phase 3 — Collaboration & Ecosystem
1. **Shared sessions**
   - Real-time sync via MCP or WebSocket backend.
   - Concurrency tests, conflict resolution strategies.
2. **Plugin marketplace**
   - Template + verifier for third-party tools/providers.
   - Security scanning before load (signed plugins).
3. **AI pair workflows**
   - Co-editing, code suggestions, lint fixes with context awareness.

### Phase 4 — Autonomy & Intelligence
1. **Adaptive planning agent**
   - Multi-turn self-management, constrained by tests/CI gates.
   - Simulation tests to ensure safe tool usage.
2. **Observability integration**
   - Connect to metrics (Prometheus, Datadog) for ops workflows.
3. **Offline-first local runtime**
   - Bundle minimal weights + fallback instructions.

## Documentation & Quality Maintenance

- Every milestone must update README, AGENTS, DEVELOPING, and ROADMAP with status/outcomes.
- Maintain ≥55% coverage (raise threshold after Phase 1).
- No disabling lint/type rules; fix root causes.
- Pre-commit hooks remain mandatory; CI must mirror local tooling.

## Next Actions (2025-10-19)

1. Complete documentation refresh (README, AGENTS, DEVELOPING) reflecting Ollama provider, clipboard export, Roadmap.
2. Add coverage + reporting scripts to CI configuration (placeholder `tasks/ci.md` backlog).
3. Prototype roadmap tracking issues/tickets.
