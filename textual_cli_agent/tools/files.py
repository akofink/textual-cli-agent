from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Iterator, List, Optional, TextIO, cast

from ..workspace import workspace_root
from .registry import tool


def _candidate_paths(path: str) -> Iterator[Path]:
    raw = Path(path).expanduser()
    yield raw
    if raw.is_absolute():
        relative = Path(*raw.parts[1:]) if raw.parts[1:] else Path(".")
        fallback = workspace_root() / relative
        if fallback != raw:
            yield fallback


def _open_with_candidates(
    path: str,
    mode: str,
    encoding: str = "utf-8",
) -> tuple[Path, TextIO]:
    last_error: Optional[OSError] = None
    for candidate in _candidate_paths(path):
        try:
            handle = cast(TextIO, open(candidate, mode, encoding=encoding))
        except OSError as exc:
            last_error = exc
            continue
        return candidate, handle
    if last_error is not None:
        raise last_error
    raise FileNotFoundError(path)


@tool(description="Read a text file.")
def file_read(path: str, encoding: str = "utf-8") -> str:
    _, handle = _open_with_candidates(path, "r", encoding)
    with handle:
        return handle.read()


@tool(description="Write text to a file (overwrites by default).")
def file_write(
    path: str, content: str, encoding: str = "utf-8", append: bool = False
) -> str:
    mode = "a" if append else "w"
    resolved, handle = _open_with_candidates(path, mode, encoding)
    with handle:
        handle.write(content)
    return str(resolved)


@tool(description="Check if a path exists.")
def path_exists(path: str) -> bool:
    for candidate in _candidate_paths(path):
        if candidate.exists():
            return True
    return False


@tool(description="Glob for files matching a pattern.")
def glob_files(pattern: str) -> List[str]:
    results = sorted(glob.glob(pattern, recursive=True))
    if results:
        return results
    candidate = Path(pattern)
    if candidate.is_absolute():
        relative = Path(*candidate.parts[1:]) if candidate.parts[1:] else Path(".")
        fallback_pattern = str(workspace_root() / relative)
        return sorted(glob.glob(fallback_pattern, recursive=True))
    return results


@tool(
    description="Find and replace in files. Returns count of replacements. Supports regex."
)
def find_replace(
    pattern: str,
    replacement: str,
    paths: List[str],
    regex: bool = False,
    encoding: str = "utf-8",
) -> int:
    count = 0
    compiled = re.compile(pattern) if regex else None
    for target in paths:
        source_path: Optional[Path] = None
        for candidate in _candidate_paths(target):
            if candidate.exists():
                source_path = candidate
                break
        if source_path is None:
            continue

        with open(source_path, "r", encoding=encoding) as handle:
            data = handle.read()

        if regex:
            assert compiled is not None
            new_content, replacements = compiled.subn(replacement, data)
        else:
            replacements = data.count(pattern)
            new_content = data.replace(pattern, replacement)

        if not replacements:
            continue

        with open(source_path, "w", encoding=encoding) as handle:
            handle.write(new_content)
        count += replacements
    return count
