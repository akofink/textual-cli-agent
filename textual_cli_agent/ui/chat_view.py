from __future__ import annotations

import logging
from typing import Any

from rich.markdown import Markdown
from rich.text import Text
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import RichLog

logger = logging.getLogger(__name__)


class ChatView(RichLog):  # type: ignore[misc]
    """RichLog derivative that handles streaming chat content and selection."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            auto_scroll=True,
            markup=True,
            highlight=False,
            max_lines=20000,
            **kwargs,
        )
        self._current_text = ""

    def get_text(self) -> str:
        """Return the plain text content for clipboard export."""
        try:
            if getattr(self, "lines", None):
                return "\n".join(strip.text for strip in self.lines)
            internal_lines = getattr(self, "_lines", None)
            if internal_lines is not None:
                collected = []
                for line in internal_lines:
                    if hasattr(line, "plain"):
                        collected.append(line.plain)
                    else:
                        collected.append(str(line))
                if collected:
                    return "\n".join(collected)
        except Exception:
            pass
        return self._current_text

    def append_text(self, text: str) -> None:
        """Append streaming text with sane wrapping."""
        self._current_text += text
        try:
            rich_text = Text(text, no_wrap=False, overflow="fold")
            self.write(rich_text)
        except Exception as e:
            logger.error(f"Error writing text to RichLog: {e}")
            try:
                self.write(text)
            except Exception:
                pass

    def append_block(self, md: str) -> None:
        """Append markdown as a formatted block with clear separation."""
        self._current_text += f"\n{md}\n"
        try:
            markdown = Markdown(md)
            self.write(markdown)
        except Exception as e:
            logger.error(f"Error rendering markdown in RichLog: {e}")
            try:
                self.write(md)
            except Exception:
                pass

    def append_hr(self) -> None:
        try:
            self.write(Markdown("\n---\n"))
        except Exception:
            try:
                self.write("\n---\n")
            except Exception:
                pass

    @property
    def allow_select(self) -> bool:  # type: ignore[override]
        return True

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Provide the currently selected text to Textual's selection system."""
        try:
            lines = [strip.text for strip in self.lines]
        except Exception:
            lines = []
        if not lines:
            return None
        extracted = selection.extract("\n".join(lines))
        if not extracted:
            return None
        return extracted, "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        self._line_cache.clear()
        self.refresh()

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        base_line = super()._render_line(y, scroll_x, width)
        line = base_line
        selection = self.text_selection

        if selection is not None:
            span = selection.get_span(y)
            if span is not None and line.cell_length > 0:
                start, end = span
                if end == -1:
                    end = scroll_x + line.cell_length

                highlight_start = max(start - scroll_x, 0)
                highlight_end = min(end - scroll_x, line.cell_length)

                if highlight_end > highlight_start:
                    selection_style = self.screen.get_component_rich_style(
                        "screen--selection"
                    )
                    parts: list[Strip] = []
                    if highlight_start > 0:
                        parts.append(line.crop(0, highlight_start))
                    highlighted = line.crop(highlight_start, highlight_end).apply_style(
                        selection_style
                    )
                    parts.append(highlighted)
                    if highlight_end < line.cell_length:
                        parts.append(line.crop(highlight_end, line.cell_length))
                    line = Strip.join(parts)

        return line.apply_offsets(scroll_x, y)
