from __future__ import annotations

from importlib import resources

SYSTEM_PROMPT_TEMPLATE = "system_prompt.txt"


def _load_template(name: str = SYSTEM_PROMPT_TEMPLATE) -> str:
    """Load a prompt template bundled with the package."""
    template_path = resources.files(__package__).joinpath(name)
    with template_path.open("r", encoding="utf-8") as handle:
        return handle.read()


def render_system_prompt(tool_names: str, workspace_root: str) -> str:
    """Render the default system prompt using the bundled template."""
    template = _load_template()
    return template.format(tool_names=tool_names, workspace_root=workspace_root)
