import subprocess
import sys


def test_cli_help_runs_without_textual() -> None:
    # Ensure help command prints without importing textual
    cmd = (
        "import sys,runpy; "
        "sys.path.insert(0, r'"
        + __import__("os").path.abspath(__import__("os").path.dirname(__file__) + "/..")
        + "'); "
        "from textual_cli_agent.cli import app; sys.argv=['textual-cli-agent','--help']; app()"
    )
    code = subprocess.run([sys.executable, "-c", cmd], capture_output=True, text=True)
    assert code.returncode == 0
    assert "Usage: textual-cli-agent" in code.stdout
