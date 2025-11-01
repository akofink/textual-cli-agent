from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional, Union

from ..workspace import workspace_root
from .registry import tool


class GitToolError(RuntimeError):
    """Raised when a git tool command fails."""

    def __init__(
        self,
        message: str,
        *,
        command: Optional[List[str]] = None,
        returncode: Optional[int] = None,
        stderr: str = "",
        stdout: str = "",
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        super().__init__(message)


def _git_executable() -> str:
    git = shutil.which("git")
    if git is None:
        raise GitToolError("git executable not found on PATH")
    return git


def _run_git(args: List[str], cwd: Optional[str] = None) -> str:
    git = _git_executable()
    command = [git, *args]
    result = subprocess.run(
        command,
        cwd=cwd or str(workspace_root()),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        message = f"{' '.join(command)} exited with {result.returncode}"
        stderr = result.stderr.strip()
        if stderr:
            message = f"{message}: {stderr}"
        raise GitToolError(
            message,
            command=command,
            returncode=result.returncode,
            stderr=stderr,
            stdout=result.stdout.strip(),
        )
    return result.stdout.rstrip("\n")


@tool(description="Show the repository status (porcelain or full).")
def git_status(porcelain: bool = True) -> str:
    args: List[str] = ["status"]
    if porcelain:
        args.extend(["--short", "--branch"])
    return _run_git(args) or "Working tree clean"


@tool(
    description=(
        "Show a git diff. Set staged=True for staged changes, pass revision for a "
        "specific commit or range, and path to limit the diff."
    )
)
def git_diff(
    revision: Optional[str] = None, path: Optional[str] = None, staged: bool = False
) -> str:
    args: List[str] = ["diff"]
    if staged:
        args.append("--cached")
    if revision:
        args.append(revision)
    if path:
        args.extend(["--", path])
    return _run_git(args)


@tool(description="Show recent commits. Limit controls the number of entries.")
def git_log(
    limit: Union[int, str] = 5, oneline: bool = True, path: Optional[str] = None
) -> str:
    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        raise GitToolError("limit must be an integer") from None
    if limit_value < 1:
        raise GitToolError("limit must be a positive integer")
    args: List[str] = ["log", f"-{limit_value}"]
    if oneline:
        args.append("--oneline")
    if path:
        args.extend(["--", path])
    try:
        return _run_git(args)
    except GitToolError as exc:
        if exc.stderr and "does not have any commits yet" in exc.stderr:
            return exc.stderr
        raise
