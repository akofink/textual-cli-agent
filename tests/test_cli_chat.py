from __future__ import annotations

from typer.testing import CliRunner

from textual_cli_agent import cli


def test_cli_chat_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--provider", "openai"])
    assert result.exit_code == 1
    assert "No API key provided" in result.output
