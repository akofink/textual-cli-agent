from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional, List

import typer
from rich.console import Console

from .providers.base import ProviderConfig, ProviderFactory
from .tools import load_tools_from_modules
from .mcp.client import McpManager

app = typer.Typer(add_completion=False, help="Textual CLI Agent")
console = Console()


def _env_default(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)


@app.command()  # type: ignore[misc]
def chat(
    provider: str = typer.Option("openai", help="LLM provider: openai|anthropic|..."),
    model: str = typer.Option(
        "gpt-5", help="Model name, e.g., gpt-5, gpt-4o, claude-3-5-sonnet-20240620"
    ),
    system: Optional[str] = typer.Option(None, help="Optional system prompt"),
    api_key: Optional[str] = typer.Option(
        None, help="API key; defaults to provider env var"
    ),
    base_url: Optional[str] = typer.Option(
        None, help="Override base URL for OpenAI-compatible endpoints"
    ),
    temperature: Optional[float] = typer.Option(
        None, help="Temperature; omit to use provider default"
    ),
    tool_module: List[str] = typer.Option(
        [], help="Python module(s) to load tools from"
    ),
    mcp_stdio: List[str] = typer.Option(
        [], help="Command(s) to start MCP servers over stdio"
    ),
    mcp_http: List[str] = typer.Option([], help="HTTP MCP server URLs"),
    mcp_grpc: List[str] = typer.Option([], help="gRPC MCP server endpoints (scaffold)"),
    # New streaming/headless options
    prompt_stdin: bool = typer.Option(
        False, help="Read a single prompt from stdin, stream response, then enter UI"
    ),
    non_interactive: bool = typer.Option(
        False, help="Headless: read prompt from stdin and print streamed response only"
    ),
) -> None:
    """Start the Textual chat UI or run in headless mode with stdin prompt."""

    # Resolve provider configuration and API key from env
    if provider.lower() == "openai":
        api_key = api_key or _env_default("OPENAI_API_KEY")
    elif provider.lower() == "anthropic":
        api_key = api_key or _env_default("ANTHROPIC_API_KEY")
    else:
        api_key = api_key or _env_default("API_KEY")

    if not api_key:
        console.print(
            "[red]No API key provided. Use --api-key or set provider env var.[/red]"
        )
        raise typer.Exit(1)

    # Load tools first so we can build a sensible default system prompt
    py_tools = load_tools_from_modules(tool_module)

    # Default system prompt if none provided
    if system is None:
        try:
            from .tools import get_tool_specs

            tool_names = ", ".join(t["name"] for t in get_tool_specs())
        except Exception:
            tool_names = (
                "http_get, file_read, file_write, path_exists, glob_files, find_replace"
            )
        system = (
            "You are a helpful AI running in a terminal-based chat UI. "
            "You have access to the local filesystem and other capabilities via callable tools. "
            f"Available tools include: {tool_names}. "
            "Use them when needed (e.g., read README.md or pyproject.toml to understand the repo). "
            "When asked about the project, explore files and summarize. Be precise, cite filenames, and avoid hallucinations. "
            "IMPORTANT: You have a limited number of tool-calling rounds per conversation (default 15). "
            "Be strategic with tool usage - batch related operations when possible and prioritize the most important tasks. "
            "If you reach the round limit, you'll be given one final opportunity to respond without tools."
        )

    prov = ProviderFactory.create(
        provider,
        ProviderConfig(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            system_prompt=system,
        ),
    )

    # Tools already loaded above

    # Setup MCP manager
    mcp_mgr = McpManager()

    async def _headless_single(prompt: str) -> int:
        from .engine import AgentEngine

        engine = AgentEngine(prov, mcp_mgr)
        messages = [{"role": "user", "content": prompt}]
        # Stream to stdout
        async for chunk in engine.run_stream(messages):
            ctype = chunk.get("type")
            if ctype == "text":
                sys.stdout.write(chunk.get("delta", ""))
                sys.stdout.flush()
            elif ctype == "tool_call":
                # simple stderr note to keep stdout clean
                console.print(
                    f"[cyan][tool call][/cyan] {chunk['name']}({chunk.get('arguments', {})})",
                    highlight=False,
                )
            elif ctype == "tool_result":
                console.print(
                    f"[magenta][tool result][/magenta] {chunk['content']}",
                    highlight=False,
                )
            elif ctype == "append_message":
                messages.append(chunk["message"])
            elif ctype == "round_complete":
                sys.stdout.write("\n")
                sys.stdout.flush()
                break
        return 0

    async def _async_main() -> None:
        await mcp_mgr.start(
            stdio_cmds=mcp_stdio, http_urls=mcp_http, grpc_endpoints=mcp_grpc
        )
        try:
            if prompt_stdin or non_interactive:
                # Read entire stdin as prompt
                prompt_data = sys.stdin.read()
                prompt = prompt_data.strip()
                if not prompt:
                    console.print(
                        "[red]No stdin data provided for --prompt-stdin/--non-interactive[/red]"
                    )
                    raise typer.Exit(1)

                if non_interactive:
                    code = await _headless_single(prompt)
                    raise typer.Exit(code)

                # Otherwise, run initial headless turn, then enter UI with the accumulated messages
                from .engine import AgentEngine

                try:
                    from .ui.app import run_textual_chat
                except Exception:
                    console.print(
                        "[red]Textual UI is not available. Please install 'textual' to run the chat UI.[/red]"
                    )
                    raise typer.Exit(1)

                engine = AgentEngine(prov, mcp_mgr)
                initial_messages = [{"role": "user", "content": prompt}]
                initial_markdown = f"**You:** {prompt}\n\n"
                async for chunk in engine.run_stream(initial_messages):
                    ctype = chunk.get("type")
                    if ctype == "text":
                        initial_markdown += chunk.get("delta", "")
                    elif ctype == "tool_call":
                        initial_markdown += f"[tool call] {chunk['name']}({chunk.get('arguments', {})})\n"
                    elif ctype == "tool_result":
                        initial_markdown += f"[tool result] {chunk['content']}\n"
                    elif ctype == "append_message":
                        initial_messages.append(chunk["message"])
                    elif ctype == "round_complete":
                        initial_markdown += "\n---\n"
                        break
                await run_textual_chat(
                    provider=prov,
                    python_tools=py_tools,
                    mcp_manager=mcp_mgr,
                    initial_messages=initial_messages,
                    initial_markdown=initial_markdown,
                )
                return

            # Default behavior: launch UI empty
            try:
                from .ui.app import run_textual_chat
            except Exception:
                console.print(
                    "[red]Textual UI is not available. Please install 'textual' to run the chat UI.[/red]"
                )
                raise typer.Exit(1)
            await run_textual_chat(
                provider=prov, python_tools=py_tools, mcp_manager=mcp_mgr
            )
        finally:
            await mcp_mgr.stop()

    asyncio.run(_async_main())
