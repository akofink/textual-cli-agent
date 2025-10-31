from textual_cli_agent.tools import (
    find_replace,
    file_read,
    file_write,
    path_exists,
    glob_files,
)
from pathlib import Path
from pytest import MonkeyPatch


def test_file_write_read_and_exists(tmp_path: Path) -> None:
    p = tmp_path / "sample.txt"
    assert not path_exists(str(p))
    file_write(str(p), "hello world")
    assert path_exists(str(p))
    assert file_read(str(p)) == "hello world"


def test_find_replace(tmp_path: Path) -> None:
    p1 = tmp_path / "a.txt"
    p2 = tmp_path / "b.txt"
    file_write(str(p1), "abc abc")
    file_write(str(p2), "abc")
    n = find_replace("abc", "xyz", [str(p1), str(p2)])
    assert n == 3
    assert file_read(str(p1)) == "xyz xyz"
    assert file_read(str(p2)) == "xyz"


def test_glob_files(tmp_path: Path) -> None:
    p1 = tmp_path / "a.txt"
    p2 = tmp_path / "sub" / "b.txt"
    p2.parent.mkdir(parents=True, exist_ok=True)
    file_write(str(p1), "x")
    file_write(str(p2), "y")
    results = glob_files(str(tmp_path / "**" / "*.txt"))
    assert str(p1) in results and str(p2) in results


def test_file_tools_respect_workspace_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    target = workspace / "pyproject.toml"
    target.write_text("hello", encoding="utf-8")

    monkeypatch.setenv("TEXTUAL_CLI_AGENT_ROOT", str(workspace))

    assert file_read("/pyproject.toml") == "hello"
    assert path_exists("/pyproject.toml")
