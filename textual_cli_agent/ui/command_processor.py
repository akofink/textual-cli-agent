from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from .chat_view import ChatView
from ..providers.base import ProviderConfig, ProviderFactory

if TYPE_CHECKING:
    from .app import ChatApp


class CommandProcessor:
    """Parse and execute slash commands entered in the input widget."""

    def __init__(self, app: "ChatApp") -> None:
        self.app = app

    def handle(self, line: str, chat: ChatView) -> bool:
        parts = line.strip().split()
        if not parts:
            return True

        cmd = parts[0].lower()
        args = parts[1:]

        def ok(msg: str) -> None:
            chat.append_block(f"[ok] {msg}")

        def err(msg: str) -> None:
            chat.append_block(f"[error] {msg}")

        if cmd == "/help":
            ok(
                "Commands:\n"
                "/help\n"
                "/config\n"
                "/model <name>\n"
                "/provider <openai|anthropic|ollama>\n"
                "/temp <float>\n"
                "/system <text>\n"
                "/auto <on|off>\n"
                "/rounds <n>\n"
                "/parallel <on|off>\n"
                "/parallel limit <n>\n"
                "/timeout <seconds>\n"
                "/tools\n"
                "/tools enable <name>\n"
                "/tools disable <name>\n"
                "/todo add <item>\n"
                "/todo remove <n>\n"
                "/todo show|hide\n"
                "/prune [n]\n"
            )
            return True

        if cmd == "/config":
            config_data: Dict[str, Any] = self.app.config.get_all()
            if config_data:
                config_lines = [
                    f"  {key}: {value}" for key, value in sorted(config_data.items())
                ]
                config_text = (
                    "Current configuration:\n" + "\n".join(config_lines) + "\n\n"
                )
                config_text += f"Config file: {self.app.config.config_file_path}"
            else:
                config_text = (
                    "No configuration saved yet.\n\n"
                    "Settings will be saved when you change them via commands like "
                    "/model, /temp, etc."
                )
            ok(config_text)
            return True

        if cmd == "/model" and args:
            model_name = " ".join(args)
            self.app._apply_provider_config(model=model_name)
            self.app.config.set("model", model_name)
            self.app._refresh_header()
            ok(f"model set -> {model_name}")
            return True

        if cmd == "/provider" and args:
            provider_name = args[0].lower()
            if provider_name not in ("openai", "anthropic", "ollama"):
                err("provider must be 'openai', 'anthropic', or 'ollama'")
                return True
            try:
                cfg = ProviderConfig(
                    model=self.app.provider.cfg.model,
                    api_key=self.app.provider.cfg.api_key,
                    base_url=self.app.provider.cfg.base_url,
                    temperature=self.app.provider.cfg.temperature,
                    system_prompt=self.app.provider.cfg.system_prompt,
                )
                new_provider = ProviderFactory.create(provider_name, cfg)
            except Exception as exc:
                err(f"failed to switch provider: {exc}")
                return True

            self.app.provider = new_provider
            self.app.engine.provider = new_provider
            self.app.config.set("provider", provider_name)
            self.app._refresh_header()
            ok(f"provider -> {provider_name}")
            return True

        if cmd == "/temp" and args:
            try:
                temperature = float(args[0])
            except Exception:
                err("temp must be a float")
                return True
            self.app._apply_provider_config(temperature=temperature)
            self.app.config.set("temperature", temperature)
            self.app._refresh_header()
            ok(f"temperature set -> {temperature}")
            return True

        if cmd == "/system" and args:
            system_prompt = " ".join(args)
            self.app._apply_provider_config(system=system_prompt)
            self.app._refresh_header()
            ok("system prompt updated")
            return True

        if cmd == "/auto" and args:
            value = args[0].lower()
            self.app.auto_continue = value in ("on", "true", "1", "yes")
            self.app.config.set("auto_continue", self.app.auto_continue)
            self.app._refresh_header()
            ok(f"auto-continue -> {self.app.auto_continue}")
            return True

        if cmd == "/rounds" and args:
            try:
                rounds = int(args[0])
            except Exception:
                err("rounds must be an integer")
                return True
            self.app.max_rounds = max(1, rounds)
            self.app.config.set("max_rounds", self.app.max_rounds)
            self.app._refresh_header()
            ok(f"max rounds -> {self.app.max_rounds}")
            return True

        if cmd == "/parallel" and args:
            if args[0] == "limit" and len(args) > 1:
                try:
                    limit = int(args[1])
                except Exception:
                    err("parallel limit must be an integer")
                    return True
                self.app.engine.concurrency_limit = max(1, limit)
                self.app._refresh_header()
                ok(f"concurrency limit -> {self.app.engine.concurrency_limit}")
                return True

            value = args[0].lower()
            if value in ("on", "off"):
                self.app.engine.concurrency_limit = None if value == "on" else 1
                self.app._refresh_header()
                ok(f"parallel -> {value}")
                return True

        if cmd == "/timeout" and args:
            try:
                seconds = float(args[0])
            except Exception:
                err("timeout must be a number (seconds)")
                return True
            self.app.engine.tool_timeout = max(1.0, seconds)
            self.app._refresh_header()
            ok(f"tool timeout -> {self.app.engine.tool_timeout}s")
            return True

        if cmd == "/tools":
            return self._handle_tools(args, chat, ok)

        if cmd == "/todo" and args:
            return self._handle_todo(args, chat, ok, err)

        if cmd == "/prune":
            return self._handle_prune(args, ok, err)

        return False

    def _handle_tools(self, args: List[str], chat: ChatView, ok_callback) -> bool:
        if not args:
            names = [
                tool.get("name", "")
                for tool in self.app.engine._combined_tool_specs()
                if tool.get("name") is not None
            ]
            enabled = (
                set(names)
                if self.app.engine.enabled_tools is None
                else set(self.app.engine.enabled_tools)
            )
            lines = ["Tools:"] + [
                ("* " if name in enabled else "  ") + name for name in names
            ]
            chat.append_block("\n".join(lines))
            return True

        if len(args) >= 2:
            subcommand = args[0].lower()
            name = " ".join(args[1:])
            if subcommand == "enable":
                if self.app.engine.enabled_tools is None:
                    self.app.engine.enabled_tools = set()
                self.app.engine.enabled_tools.add(name)
                self.app._refresh_header()
                ok_callback(f"enabled tool -> {name}")
                return True
            if subcommand == "disable":
                if self.app.engine.enabled_tools is None:
                    self.app.engine.enabled_tools = set(
                        name
                        for name in (
                            tool.get("name")
                            for tool in self.app.engine._combined_tool_specs()
                        )
                        if name is not None
                    )
                self.app.engine.enabled_tools.discard(name)
                self.app._refresh_header()
                ok_callback(f"disabled tool -> {name}")
                return True

        return False

    def _handle_todo(
        self,
        args: List[str],
        chat: ChatView,
        ok_callback,
        err_callback,
    ) -> bool:
        subcommand = args[0].lower()
        if subcommand == "add" and len(args) > 1:
            item = " ".join(args[1:])
            self.app._todos.append(item)
            ok_callback(f"todo added -> {item}")
            if self.app._show_todo:
                self.app._render_todos(chat)
            return True
        if subcommand == "remove" and len(args) > 1:
            try:
                index = int(args[1]) - 1
                if 0 <= index < len(self.app._todos):
                    removed = self.app._todos.pop(index)
                    ok_callback(f"todo removed -> {removed}")
                    if self.app._show_todo:
                        self.app._render_todos(chat)
                else:
                    err_callback("index out of range")
            except Exception:
                err_callback("usage: /todo remove <n>")
            return True
        if subcommand in ("show", "hide"):
            self.app._show_todo = subcommand == "show"
            self.app.config.set("show_todo", self.app._show_todo)
            self.app._render_todos(chat)
            ok_callback(f"todo -> {subcommand}")
            return True
        err_callback("usage: /todo add <item> | /todo remove <n> | /todo show|hide")
        return True

    def _handle_prune(self, args: List[str], ok_callback, err_callback) -> bool:
        prune_count = 10
        if args:
            try:
                prune_count = int(args[0])
            except Exception:
                err_callback("prune count must be an integer")
                return True

        original_count = len(self.app.messages)
        if original_count <= prune_count:
            ok_callback(
                f"No pruning needed. Current: {original_count} messages, keep: {prune_count}"
            )
            return True

        pruned_messages: List[Dict[str, Any]] = []
        if self.app.messages and self.app.messages[0].get("role") == "system":
            pruned_messages.append(self.app.messages[0])
            pruned_messages.extend(self.app.messages[-(prune_count - 1) :])
        else:
            pruned_messages = self.app.messages[-prune_count:]

        removed_count = original_count - len(pruned_messages)
        self.app.messages = pruned_messages

        ok_callback(
            f"Pruned {removed_count} messages. Kept {len(pruned_messages)} messages."
        )
        return True
