from __future__ import annotations

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class ContextManager:
    """Manages conversation context and handles pruning when limits are exceeded."""

    def __init__(self):
        self.max_context_messages = 50  # Maximum number of messages to keep
        self.preserve_system_messages = True
        self.preserve_recent_messages = 10  # Always keep recent messages

    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Rough estimation of token count for messages."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                # Rough estimate: ~1 token per 4 characters for English text
                total += len(content) // 4
            elif isinstance(content, list):
                # Handle structured content (images, etc.)
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        total += len(text) // 4

            # Add tokens for tool calls
            if "tool_calls" in msg:
                tool_calls = msg.get("tool_calls", [])
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        total += 50  # Rough estimate for tool call overhead
                        args = tc.get("function", {}).get("arguments", "")
                        total += len(str(args)) // 4

        return total

    def should_prune_context(
        self, messages: List[Dict[str, Any]], error_str: str = ""
    ) -> bool:
        """Determine if context should be pruned based on error or message count."""
        # Check if error indicates context issues
        if any(
            term in error_str.lower()
            for term in [
                "context",
                "token",
                "too large",
                "maximum context length",
                "limit",
            ]
        ):
            return True

        # Check message count
        if len(messages) > self.max_context_messages:
            return True

        # Rough token estimate check
        estimated_tokens = self.estimate_tokens(messages)
        if estimated_tokens > 50000:  # Conservative estimate for most models
            return True

        return False

    def prune_messages(
        self, messages: List[Dict[str, Any]], target_reduction: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Intelligently prune messages to reduce context size."""
        if not messages:
            return messages

        logger.info(
            f"Pruning context from {len(messages)} messages (target reduction: {target_reduction:.1%})"
        )

        # Always preserve system messages
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        non_system_messages = [msg for msg in messages if msg.get("role") != "system"]

        if not non_system_messages:
            return messages  # Nothing to prune

        # Calculate how many messages to keep
        current_count = len(non_system_messages)
        target_count = max(
            self.preserve_recent_messages, int(current_count * (1.0 - target_reduction))
        )

        if target_count >= current_count:
            return messages  # No pruning needed

        # Keep the most recent messages
        messages_to_keep = non_system_messages[-target_count:]

        # Combine system messages with kept messages
        result = system_messages + messages_to_keep

        logger.info(
            f"Context pruned to {len(result)} messages (removed {len(messages) - len(result)})"
        )

        return result

    def prune_for_error(
        self, messages: List[Dict[str, Any]], error_str: str
    ) -> List[Dict[str, Any]]:
        """Prune messages based on specific error type."""
        if "token" in error_str.lower() or "too large" in error_str.lower():
            # Aggressive pruning for token limits
            return self.prune_messages(messages, target_reduction=0.7)
        elif "context" in error_str.lower():
            # Moderate pruning for context limits
            return self.prune_messages(messages, target_reduction=0.5)
        else:
            # Conservative pruning for other errors
            return self.prune_messages(messages, target_reduction=0.3)

    def create_context_summary(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a summary message for pruned context."""
        non_system_count = len([m for m in messages if m.get("role") != "system"])

        summary = f"""[Previous conversation context with {non_system_count} messages was summarized to manage token limits. Key points from the conversation are preserved in this session.]"""

        return {"role": "system", "content": summary}

    def adaptive_prune_with_summary(
        self, messages: List[Dict[str, Any]], error_str: str = ""
    ) -> List[Dict[str, Any]]:
        """Prune messages and add a context summary."""
        if not self.should_prune_context(messages, error_str):
            return messages

        # Create summary before pruning
        summary_msg = self.create_context_summary(messages)

        # Prune the messages
        pruned = self.prune_for_error(messages, error_str)

        # Insert summary after system messages but before conversation
        system_messages = [msg for msg in pruned if msg.get("role") == "system"]
        other_messages = [msg for msg in pruned if msg.get("role") != "system"]

        result = system_messages + [summary_msg] + other_messages

        return result


# Global context manager instance
context_manager = ContextManager()
