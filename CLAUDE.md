# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a Textual-based CLI LLM agent with MCP support and pluggable Python tools. The application supports OpenAI and Anthropic providers with a rich terminal UI, comprehensive error handling, and 58% test coverage with defensive programming patterns.

## Development Commands

### Environment Setup
- **Initial setup**: `uv sync --extra dev`
- **Pre-commit hooks**: `pre-commit install` (install via homebrew if uv version doesn't work)

### Code Quality & Testing
- **Run all tests**: `uv run pytest`
- **Run single test**: `uv run pytest tests/test_specific.py::test_function_name -v`
- **Test with coverage**: `uv run coverage run -m pytest && uv run coverage report --show-missing`
- **Type checking**: `uv run mypy .`
- **Linting**: `uv run ruff check .` and `uv run ruff format --check .`
- **Format code**: `uv run ruff format .`
- **Run pre-commit hooks**: `uv run pre-commit run --all-files`

### Running the Application
- **Basic chat**: `uv run textual-cli-agent chat --provider openai --model gpt-4o`
- **With tools**: `uv run textual-cli-agent chat --provider anthropic --model claude-3-5-sonnet-20240620 --tool-module my_module.tools`
- **Headless mode**: `echo "What is 2+2?" | uv run textual-cli-agent chat --provider openai --model gpt-4o --non-interactive`
- **With MCP servers**: `uv run textual-cli-agent chat --provider openai --model gpt-4o --mcp-stdio "node server.js"`

## Architecture Overview

### Core Components

**AgentEngine** (`textual_cli_agent/engine.py`)
- Central orchestrator that coordinates between providers, tools, and the UI
- Handles message streaming, tool execution with 60-second timeouts, and error recovery
- Implements comprehensive validation and defensive programming patterns
- Manages conversation flow and maintains proper provider-specific message formats

**Provider System** (`textual_cli_agent/providers/`)
- Abstract base class defines provider-agnostic interface for LLM interactions
- OpenAI and Anthropic providers implement streaming completions with tool calling
- Each provider handles its own message formatting and error handling
- Providers translate between generic ToolSpec format and provider-specific schemas

**Tool System** (`textual_cli_agent/tools/`)
- Decorator-based tool registration system using `@tool()`
- Built-in tools: http_get, file_read/write, path_exists, glob_files, find_replace
- Supports both sync and async tool functions with automatic detection
- Tools are automatically converted to JSON schema for provider consumption

**MCP Integration** (`textual_cli_agent/mcp/`)
- Model Context Protocol client supporting stdio and HTTP transports
- Graceful degradation when MCP SDK is not available
- Automatic tool discovery and registration from connected MCP servers
- Connection recovery and error handling for unreliable MCP servers

**UI System** (`textual_cli_agent/ui/app.py`)
- Textual-based TUI with RichLog for enhanced text interaction (Toad-inspired)
- 10,000-line scrollback buffer with smooth auto-scrolling
- Enhanced keyboard shortcuts: Ctrl+L (clear), Home/End (navigation), Ctrl+Y (copy)
- Comprehensive error handling with visual/audio feedback
- Supports both interactive and headless modes

### Data Flow

1. **CLI Entry**: `cli.py` parses arguments, creates provider config, loads tool modules
2. **Provider Setup**: Creates provider instance (OpenAI/Anthropic) with configuration
3. **Tool Registration**: Loads built-in tools + custom modules + MCP server tools
4. **Engine Initialization**: AgentEngine coordinates provider and available tools
5. **UI Launch**: ChatApp creates interface, handles user input and streaming responses
6. **Message Processing**: User input → AgentEngine → Provider → Tool execution → UI display

### Key Design Patterns

**Defensive Programming**: All components include comprehensive error handling with graceful degradation. Errors are logged and displayed to users rather than crashing the application.

**Provider Abstraction**: The base Provider class enables adding new LLM providers by implementing `completions_stream()` and `list_tools_format()` methods.

**Streaming Architecture**: All interactions use async streaming for responsive UI updates and real-time feedback during long-running operations.

**Modular Tool System**: Tools are self-contained functions with automatic schema generation, enabling easy extension of agent capabilities.

## Testing Strategy

The codebase maintains **58% test coverage** with focus on error handling scenarios:

- **Provider Tests**: API failures, stream errors, malformed responses, JSON parsing errors
- **Engine Tests**: Tool execution, timeouts, message validation, error recovery
- **UI Tests**: Rendering errors, input failures, keyboard shortcuts, text interaction
- **Tool Tests**: Built-in tool functionality, argument validation, error handling
- **Integration Tests**: End-to-end scenarios combining multiple components

**Test Configuration**:
- Coverage threshold: 55% (fail_under in pyproject.toml)
- Pre-commit hook runs tests with coverage check
- Async test mode enabled globally via pytest configuration

## Configuration Files

- **pyproject.toml**: Project dependencies, scripts, tool configuration, coverage settings
- **.pre-commit-config.yaml**: Automated quality checks (ruff, mypy, pytest)
- **uv.lock**: Dependency lockfile for reproducible environments

## Quality Standards

- TODO: Ensure chat_export*.txt files are always ignored and not committed to git.


- **Type Safety**: Full mypy coverage with strict checking enabled
- **Code Style**: Ruff + Black for consistent formatting and linting
- **Pre-commit Hooks**: Automatic quality checks on every commit
- **Error Handling**: Comprehensive try/catch blocks with user-friendly error messages
- **Test Coverage**: Minimum 55% with focus on critical error paths
