from __future__ import annotations

import glob
import os
import re
from typing import List

from .registry import tool


@tool(description="Read a text file.")
def file_read(path: str, encoding: str = "utf-8") -> str:
    with open(path, "r", encoding=encoding) as handle:
        return handle.read()


@tool(description="Write text to a file (overwrites by default).")
def file_write(
    path: str, content: str, encoding: str = "utf-8", append: bool = False
) -> str:
    mode = "a" if append else "w"
    with open(path, mode, encoding=encoding) as handle:
        handle.write(content)
    return path


@tool(description="Check if a path exists.")
def path_exists(path: str) -> bool:
    return os.path.exists(path)


@tool(description="Glob for files matching a pattern.")
def glob_files(pattern: str) -> List[str]:
    return sorted(glob.glob(pattern, recursive=True))


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
        try:
            with open(target, "r", encoding=encoding) as handle:
                data = handle.read()
        except FileNotFoundError:
            continue

        if regex:
            assert compiled is not None
            new_content, replacements = compiled.subn(replacement, data)
        else:
            replacements = data.count(pattern)
            new_content = data.replace(pattern, replacement)

        if not replacements:
            continue

        with open(target, "w", encoding=encoding) as handle:
            handle.write(new_content)
        count += replacements
    return count
