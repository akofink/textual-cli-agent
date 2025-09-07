from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import ConfigManager


@dataclass
class SessionInfo:
    id: str
    path: Path
    created: datetime


class SessionStore:
    """Manage chat session logs stored under XDG config in a sessions/ directory.

    Each session is a JSON array of event dicts. We append events over time to persist
    context between runs. If pruning is needed, entries are not removed; instead they
    are marked with {"pruned": true}.
    """

    def __init__(self, config: Optional[ConfigManager] = None) -> None:
        self.config = config or ConfigManager()
        self.sessions_dir = self.config.config_file_path.parent / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._current_path: Optional[Path] = None

    def start_session(self, session_id: Optional[str] = None) -> Path:
        ts = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        # Preserve existing naming style: tools_<timestamp>.json
        self._current_path = self.sessions_dir / f"tools_{ts}.json"
        if not self._current_path.exists():
            self._write_all([])
        return self._current_path

    def resume_session(self, session_id_or_path: str | Path) -> Path:
        """Point the store at an existing session file without modifying it."""
        p = self._resolve_path(session_id_or_path)
        self._current_path = p
        if not p.exists():
            # Initialize empty if missing
            self._write_all([], p)
        return p

    @property
    def current_path(self) -> Optional[Path]:
        return self._current_path

    def _read_all(self, path: Optional[Path] = None) -> List[Dict[str, Any]]:
        p = path or self._current_path
        if p is None or not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _write_all(
        self, events: List[Dict[str, Any]], path: Optional[Path] = None
    ) -> None:
        p = path or self._current_path
        if p is None:
            return
        p.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_event(self, event: Dict[str, Any]) -> None:
        """Append an event to the current session file."""
        if self._current_path is None:
            self.start_session()
        events = self._read_all()
        event = {"timestamp": datetime.now().isoformat(), **event}
        events.append(event)
        self._write_all(events)

    def list_sessions(self) -> List[SessionInfo]:
        infos: List[SessionInfo] = []
        for p in sorted(self.sessions_dir.glob("tools_*.json")):
            try:
                # derive created from filename
                sid = p.stem.replace("tools_", "")
                created = datetime.strptime(sid, "%Y%m%d_%H%M%S")
            except Exception:
                sid = p.stem
                created = datetime.fromtimestamp(p.stat().st_mtime)
            infos.append(SessionInfo(id=sid, path=p, created=created))
        return infos

    def load_entries(self, session_id_or_path: str | Path) -> List[Dict[str, Any]]:
        p = self._resolve_path(session_id_or_path)
        return self._read_all(p)

    def _resolve_path(self, session_id_or_path: str | Path) -> Path:
        if isinstance(session_id_or_path, Path):
            return session_id_or_path
        # If it's a bare id, construct path
        candidate = self.sessions_dir / (
            session_id_or_path
            if session_id_or_path.endswith(".json")
            else f"tools_{session_id_or_path}.json"
        )
        return candidate

    def mark_all_pruned(self, session_id_or_path: Optional[str | Path] = None) -> None:
        p = (
            self._resolve_path(session_id_or_path)
            if session_id_or_path
            else self._current_path
        )
        if p is None:
            return
        events = self._read_all(p)
        for e in events:
            e["pruned"] = True
        self._write_all(events, p)

    def mark_entry_pruned_by_index(
        self, index: int, session_id_or_path: Optional[str | Path] = None
    ) -> None:
        p = (
            self._resolve_path(session_id_or_path)
            if session_id_or_path
            else self._current_path
        )
        if p is None:
            return
        events = self._read_all(p)
        if 0 <= index < len(events):
            events[index]["pruned"] = True
            self._write_all(events, p)

    def reconstruct_messages(
        self, session_id_or_path: str | Path
    ) -> List[Dict[str, Any]]:
        """Rebuild a minimal message list from session entries, ignoring entries marked pruned.
        Includes user prompts and assistant text blocks.
        """
        entries = self.load_entries(session_id_or_path)
        messages: List[Dict[str, Any]] = []
        for e in entries:
            if e.get("pruned"):
                continue
            et = e.get("event_type") or e.get("type")
            if et == "user_prompt":
                content = e.get("content", "")
                messages.append({"role": "user", "content": content})
            elif et == "assistant_text":
                content = e.get("content", "")
                if content:
                    messages.append({"role": "assistant", "content": content})
        return messages
