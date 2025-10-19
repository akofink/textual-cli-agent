from __future__ import annotations

from textual_cli_agent.context_manager import ContextManager


def build_messages(count: int, role: str = "user") -> list[dict[str, str]]:
    return [{"role": role, "content": f"message {idx}"} for idx in range(count)]


def test_estimate_tokens_counts_text_and_tool_calls() -> None:
    manager = ContextManager()
    messages = [
        {"role": "user", "content": "abcd" * 4},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "abcd" * 4}],
            "tool_calls": [
                {"function": {"arguments": '{"foo": "bar"}'}},
            ],
        },
    ]
    tokens = manager.estimate_tokens(messages)
    # 4 strings contribute at least 4 tokens, plus 50 for tool_call and args size
    assert tokens >= 60


def test_should_prune_context_by_error_and_length() -> None:
    manager = ContextManager()
    assert manager.should_prune_context([], "context window exceeded")
    manager.max_context_messages = 1
    assert manager.should_prune_context(build_messages(3))


def test_should_prune_context_by_token_estimate() -> None:
    manager = ContextManager()
    big_message = [{"role": "user", "content": "0123" * 60_000}]
    assert manager.should_prune_context(big_message)


def test_prune_messages_preserves_system_and_recent() -> None:
    manager = ContextManager()
    manager.preserve_recent_messages = 2
    messages = build_messages(3)
    messages.append({"role": "system", "content": "sys"})
    pruned = manager.prune_messages(messages, target_reduction=0.5)
    assert any(msg["role"] == "system" for msg in pruned)
    assert len([m for m in pruned if m["role"] != "system"]) == 2


def test_prune_for_error_levels() -> None:
    manager = ContextManager()
    messages = build_messages(10)
    aggressive = manager.prune_for_error(messages, "token limit hit")
    moderate = manager.prune_for_error(messages, "context overflow")
    conservative = manager.prune_for_error(messages, "misc failure")
    assert len(aggressive) <= len(moderate) <= len(conservative)


def test_adaptive_prune_with_summary_inserts_summary() -> None:
    manager = ContextManager()
    manager.max_context_messages = 1
    messages = build_messages(5)
    result = manager.adaptive_prune_with_summary(messages)
    system_summary = [msg for msg in result if msg["role"] == "system"]
    assert system_summary
    assert "Previous conversation context" in system_summary[0]["content"]
