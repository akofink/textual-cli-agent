from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from .tool_panel import ToolPanel

logger = logging.getLogger(__name__)


class ToolManager:
    """Coordinate tool call bookkeeping and panel updates."""

    def __init__(
        self,
        panel_lookup: Callable[[], Optional[ToolPanel]],
        session_store,
    ) -> None:
        self._panel_lookup = panel_lookup
        self._session_store = session_store
        self.tool_calls_by_id: Dict[str, Dict[str, Any]] = {}
        self.pending_results: Dict[str, Any] = {}

    @staticmethod
    def parse_payload(payload: Any) -> Any:
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except Exception:
                return payload
        return payload

    def get_panel(self) -> Optional[ToolPanel]:
        try:
            panel = self._panel_lookup()
        except Exception:
            panel = None
        return panel

    def apply_tool_result(self, tool_id: str, content: Any) -> None:
        if not tool_id:
            return
        if tool_id in self.tool_calls_by_id:
            self.tool_calls_by_id[tool_id]["result"] = content

        panel = self.get_panel()
        if not panel:
            return

        error_text: Optional[str] = None
        if isinstance(content, dict) and "error" in content:
            error_text = str(content.get("error"))

        try:
            if error_text:
                panel.update_tool_result(tool_id, error=error_text)
            else:
                panel.update_tool_result(tool_id, result=content)
        except Exception as e:
            logger.debug(f"Failed to update tool panel result for {tool_id}: {e}")

    def record_tool_call(self, tool_id: str, name: str, raw_args: Any) -> None:
        if not tool_id:
            return

        parsed_args = self.parse_payload(raw_args)
        self.tool_calls_by_id[tool_id] = {"name": name, "arguments": parsed_args}

        panel = self.get_panel()
        if panel:
            call_args = (
                parsed_args if isinstance(parsed_args, dict) else {"value": parsed_args}
            )
            try:
                panel.add_tool_call(tool_id, name, call_args)
            except Exception as e:
                logger.debug(f"Failed to add tool call {tool_id} to panel: {e}")

        if tool_id in self.pending_results:
            content = self.pending_results.pop(tool_id)
            self.apply_tool_result(tool_id, content)

    def record_tool_result(self, tool_id: str, raw_content: Any) -> None:
        if not tool_id:
            return

        parsed_content = self.parse_payload(raw_content)
        self.pending_results[tool_id] = parsed_content

        if tool_id in self.tool_calls_by_id:
            content = self.pending_results.pop(tool_id, parsed_content)
            self.apply_tool_result(tool_id, content)

    def write_debug(self, tool_id: str, event_type: str, data: Dict[str, Any]) -> None:
        try:
            entry = {
                "tool_id": tool_id,
                "event_type": event_type,
                "data": data,
            }
            self._session_store.add_event(entry)
        except Exception as e:
            logger.warning(f"Failed to write tool debug info: {e}")

    @staticmethod
    def result_summary(content: Any) -> str:
        if isinstance(content, str):
            if len(content) > 100:
                return f"{content[:97]}..."
            return content or "(empty)"
        if isinstance(content, dict):
            if "error" in content:
                return f"Error: {content.get('error', 'Unknown')}"
            if "success" in content:
                return "Success"
            return f"Dict with {len(content)} keys"
        if isinstance(content, list):
            return f"List with {len(content)} items"
        return str(content)[:100]
