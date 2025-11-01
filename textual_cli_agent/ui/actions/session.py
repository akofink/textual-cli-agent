from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, cast

from ..chat_view import ChatView

if TYPE_CHECKING:
    from ..app import ChatApp


class SessionActionsMixin:
    """Actions that interact with the persisted session store."""

    _session_store: Any
    messages: List[Dict[str, Any]]

    def action_list_sessions(self) -> None:
        app = cast("ChatApp", self)
        sessions = app._session_store.list_sessions()
        if not sessions:
            try:
                chat = app.query_one("#chat", ChatView)
                chat.append_block("[ok] No sessions found.")
            except Exception:
                pass
            return
        lines = ["[sessions]"]
        for idx, session in enumerate(sessions):
            lines.append(
                f"{idx + 1}. {session.id}  ({session.created:%Y-%m-%d %H:%M:%S})"
            )
        try:
            chat = app.query_one("#chat", ChatView)
            chat.append_block("\n".join(lines))
        except Exception:
            pass

    def action_resume_session(self) -> None:
        app = cast("ChatApp", self)
        sessions = app._session_store.list_sessions()
        if not sessions:
            try:
                chat = app.query_one("#chat", ChatView)
                chat.append_block("[error] No sessions to resume.")
            except Exception:
                pass
            return

        latest = sorted(sessions, key=lambda s: s.created)[-1]
        app._session_store.resume_session(latest.id)
        app.messages = app._session_store.reconstruct_messages(latest.id)

        try:
            chat = app.query_one("#chat", ChatView)
            chat.clear()
            chat._current_text = ""
            chat.append_block(f"[ok] Resumed session {latest.id}")
            for message in app.messages:
                role = message.get("role")
                content = message.get("content", "")
                if role == "user":
                    chat.append_block(f"**You:**\n{content}")
                else:
                    chat.append_block(content)
                chat.append_hr()
        except Exception:
            pass
