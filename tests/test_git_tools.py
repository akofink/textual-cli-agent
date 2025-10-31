from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from textual_cli_agent.tools import git_diff, git_log, git_status
from textual_cli_agent.tools.git import GitToolError


def _git() -> str:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git executable not available")
    return git


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        [_git(), *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(["init"], repo)
    _run_git(["config", "user.name", "Test User"], repo)
    _run_git(["config", "user.email", "test@example.com"], repo)
    return repo


def test_git_status_reports_changes(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.setenv("TEXTUAL_CLI_AGENT_ROOT", str(repo))

    (repo / "example.txt").write_text("hello\n", encoding="utf-8")
    status = git_status()
    assert "?? example.txt" in status

    _run_git(["add", "example.txt"], repo)
    status_after_add = git_status()
    assert "A  example.txt" in status_after_add

    _run_git(["commit", "-m", "initial commit"], repo)
    clean_status = git_status(porcelain=False)
    assert "nothing to commit" in clean_status


def test_git_diff_and_log(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.setenv("TEXTUAL_CLI_AGENT_ROOT", str(repo))

    file_path = repo / "example.txt"
    file_path.write_text("hello\n", encoding="utf-8")
    _run_git(["add", "example.txt"], repo)
    _run_git(["commit", "-m", "initial commit"], repo)

    file_path.write_text("hello\nworld\n", encoding="utf-8")
    diff_output = git_diff(path="example.txt")
    assert "+world" in diff_output
    assert "@@" in diff_output

    _run_git(["add", "example.txt"], repo)
    staged_diff = git_diff(path="example.txt", staged=True)
    assert "+world" in staged_diff

    log_output = git_log(limit=1)
    assert "initial commit" in log_output


def test_git_log_rejects_invalid_limit(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.setenv("TEXTUAL_CLI_AGENT_ROOT", str(repo))
    with pytest.raises(GitToolError):
        git_log(limit=0)


def test_git_log_handles_repo_without_commits(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.setenv("TEXTUAL_CLI_AGENT_ROOT", str(repo))
    message = git_log(limit=5)
    assert "does not have any commits yet" in message
