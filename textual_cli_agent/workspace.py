from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ROOT_ENV = "TEXTUAL_CLI_AGENT_ROOT"


def workspace_root() -> Path:
    """Return the workspace root directory for tool resolution."""
    override = os.environ.get(WORKSPACE_ROOT_ENV)
    if override:
        return Path(override)
    return Path.cwd()
