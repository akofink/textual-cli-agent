import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from textual_cli_agent.session_store import SessionStore


def test_session_store_persists_events_and_lists_sessions():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            store = SessionStore()
            path = store.start_session("20240101_010203")
            store.add_event({"event_type": "user_prompt", "content": "hello"})
            store.add_event({"event_type": "assistant_text", "content": "world"})

            # Verify content
            data = json.loads(Path(path).read_text())
            assert len(data) == 2
            assert data[0]["event_type"] == "user_prompt"
            assert data[1]["event_type"] == "assistant_text"

            # List sessions
            sessions = store.list_sessions()
            assert any(s.id == "20240101_010203" for s in sessions)

            # Mark pruned
            store.mark_all_pruned("20240101_010203")
            data2 = json.loads(Path(path).read_text())
            assert all(e.get("pruned") for e in data2)
