# textual-cli-agent

A robust Textual-based CLI LLM agent with comprehensive error handling, MCP support, and pluggable Python tools. It supports popular model providers (OpenAI, Anthropic, and Ollama) out of the box, including GPT-5 (as a model name for OpenAI-compatible endpoints) and Claude 4 Sonnet.

## Features

- **Terminal UI** built with Textual with defensive error handling
- **Provider-agnostic** agent core with adapters for OpenAI, Anthropic, and Ollama
- **Robust error handling** with graceful degradation and timeout protection
- **Tool calling** and Python tool registry via a simple decorator
- **MCP client** to connect to servers via stdio and HTTP (gRPC scaffold provided)
- **Comprehensive testing** with 58% coverage and defensive programming patterns
- **Extensible design**: add your own providers, tools, and MCP transports

## Quick start (using uv)

Prerequisites: Python 3.11+ and [uv](https://github.com/astral-sh/uv)

```bash
# From the repository root
uv run textual-cli-agent --help
```

Or install locally into an environment managed by uv:

```bash
uv sync
uv run textual-cli-agent --help
```

## Environment variables

- `OPENAI_API_KEY` for OpenAI-compatible endpoints (includes OpenAI, Azure OpenAI with `--base-url`, local gateways)
- `ANTHROPIC_API_KEY` for Anthropic (Claude)
- Ollama runs locally by default and does not require an API key; use `--base-url` to point at a remote Ollama instance if needed.

You can override with CLI flags.

## Usage

### Streaming from stdin and headless mode

- Preload the UI with a streamed first response from stdin:

```bash
echo "Summarize this project." | uv run textual-cli-agent chat --provider openai --model gpt-4o --prompt-stdin
```

- Run non-interactive (headless) and print streamed response to stdout only:

```bash
echo "What is 2+2?" | uv run textual-cli-agent chat --provider openai --model gpt-4o --non-interactive
```


Start a chat against OpenAI (any OpenAI-compatible endpoint) with GPT-5:

```bash
uv run textual-cli-agent chat \
  --provider openai \
  --model gpt-5 \
  --system "You are a helpful assistant" \
  --tool-module my_project.agent_tools
```

Start a chat against Anthropic Claude 4 Sonnet (or your available Claude Sonnet model):

```bash
uv run textual-cli-agent chat \
  --provider anthropic \
  --model claude-4-sonnet \
  --system "You are a helpful assistant"
```

Chat with a local Ollama model (the daemon must be running):

```bash
uv run textual-cli-agent chat \
  --provider ollama \
  --model llama3 \
  --system "You are a helpful assistant"
```

Connect to one or more MCP servers:

```bash
# stdio transport (spawn a process that speaks MCP on stdio)
uv run textual-cli-agent chat \
  --provider openai --model gpt-4o \
  --mcp-stdio "node ./server.js --flag" \
  --mcp-stdio "./my_mcp_server"

# HTTP transport
uv run textual-cli-agent chat \
  --provider openai --model gpt-4o \
  --mcp-http http://localhost:8011
```

If a connected MCP server exposes tools, they appear to the model as normal callable tools.

## Built-in tools

- http_get(url, timeout=20.0, headers=None) -> str
- file_read(path, encoding="utf-8") -> str
- file_write(path, content, encoding="utf-8", append=False) -> str
- path_exists(path) -> bool
- glob_files(pattern) -> list[str]
- find_replace(pattern, replacement, paths, regex=False, encoding="utf-8") -> int

## Writing custom Python tools

Create a module and decorate functions with `@tool`:

```python
# my_project/agent_tools.py
from textual_cli_agent.tools import tool

@tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b

@tool(name="search_web")
async def search(query: str, num_results: int = 5) -> list[str]:
    """Search the web and return titles (example stub)."""
    return [f"Result {i} for {query}" for i in range(num_results)]
```

Then pass your module via CLI:

```bash
uv run textual-cli-agent chat --provider openai --model gpt-4o --tool-module my_project.agent_tools
```

The agent will advertise your tools to the selected provider and automatically execute tool calls from the model.

## Textual UI

- Type your prompt and press Enter
- Tool call results and assistant messages are streamed into the chat view
- **Robust error handling**: API errors, stream processing failures, and UI errors are handled gracefully
- **Keyboard shortcuts**:
  - Ctrl+C, Ctrl+Q, Ctrl+D to exit
  - Ctrl+Y to copy chat history
- **Timeout protection**: Tool execution is protected with 60-second timeouts
- All errors are logged and displayed in a user-friendly format

## Extending providers

Providers implement a simple async interface in `textual_cli_agent/providers/base.py`. See `openai_provider.py`, `anthropic_provider.py`, and `ollama_provider.py` for reference. Add a new provider class and register it in `ProviderFactory` (and expose it via the CLI) if you need more.

## Limitations and notes

- HTTP MCP is supported via the Python MCP SDK, if available. If the SDK is not present, MCP features are disabled gracefully.
- gRPC transport is scaffolded but may require an additional package or plugin depending on your MCP server implementation.
- Tool argument schemas come from function type hints. Prefer `pydantic` models for complex objects.

## Development

See DEVELOPING.md for setup details and AGENTS.md for contributor guidelines.

```bash
uv sync --extra dev
uv run pre-commit install
uv run pytest
uv run textual-cli-agent chat --provider openai --model gpt-4o
```

## License

MIT
