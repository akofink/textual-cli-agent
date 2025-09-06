from __future__ import annotations

import asyncio
import importlib
import inspect
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Union,
    TypeVar,
    cast,
    get_origin,
    get_args,
)
import os
import re
import glob

import httpx

from pydantic import BaseModel, Field
from .providers.base import ToolSpec
from .todo_store import (
    list_todos as _list_todos,
    add_todo as _add_todo,
    remove_todo as _remove_todo,
    set_todo as _set_todo,
)


R = TypeVar("R")
ToolFunc = Callable[..., Union[R, Coroutine[Any, Any, R]]]


@dataclass
class RegisteredTool:
    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable[..., Any]
    is_async: bool


_TOOL_REGISTRY: Dict[str, RegisteredTool] = {}


def tool(
    name: Optional[str] = None, description: Optional[str] = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a function as a tool.

    - Infers JSON schema from type hints; for complex types prefer Pydantic models.
    - Async and sync functions are both supported.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or func.__name__
        desc = description or inspect.getdoc(func) or ""
        schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}

        sig = inspect.signature(func)
        for pname, param in sig.parameters.items():
            if pname == "self":
                continue
            ann = param.annotation
            default = param.default
            is_required = default is inspect._empty
            schema["properties"][pname] = _annotation_to_schema(ann)
            if is_required:
                schema["required"].append(pname)

        _TOOL_REGISTRY[tool_name] = RegisteredTool(
            name=tool_name,
            description=desc,
            parameters=schema,
            func=func,
            is_async=inspect.iscoroutinefunction(func),
        )
        return func

    return decorator


def _annotation_to_schema(ann: Any) -> Dict[str, Any]:
    # Pydantic model
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        model_t = cast(type[BaseModel], ann)
        schema = cast(Dict[str, Any], model_t.model_json_schema())
        return schema
    # typing constructs
    origin = get_origin(ann)
    if origin is list or origin is List:
        (arg,) = get_args(ann) if get_args(ann) else (str,)
        return {"type": "array", "items": _annotation_to_schema(arg)}
    if origin is dict or origin is Dict:
        return {"type": "object"}
    # Builtins
    mapping = {int: "integer", float: "number", str: "string", bool: "boolean"}
    if ann in mapping:
        return {"type": mapping[ann]}
    # Fallback
    return {"type": "string"}


def get_tool_specs() -> List[ToolSpec]:
    specs: List[ToolSpec] = [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in _TOOL_REGISTRY.values()
    ]
    return specs


async def execute_tool(name: str, arguments: Dict[str, Any]) -> Any:
    if name not in _TOOL_REGISTRY:
        raise KeyError(f"Unknown tool: {name}")
    t = _TOOL_REGISTRY[name]
    if t.is_async:
        return await t.func(**arguments)
    # run sync in thread to avoid blocking loop
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: t.func(**arguments))


def load_tools_from_modules(modules: List[str]) -> List[RegisteredTool]:
    for mod in modules:
        importlib.import_module(mod)
    return list(_TOOL_REGISTRY.values())


# -------------------- Built-in Tools --------------------

# TODO Tools so the AI can manage TODO list


@tool(description="List TODO items.")
async def todo_list() -> List[str]:
    return await _list_todos()


@tool(description="Add a TODO item.")
async def todo_add(item: str) -> str:
    await _add_todo(item)
    return item


@tool(description="Remove a TODO item by 1-based index.")
async def todo_remove(index: int) -> bool:
    # Accept 1-based index in tool
    return await _remove_todo(max(0, index - 1))


@tool(description="Edit a TODO item by 1-based index.")
async def todo_edit(index: int, item: str) -> bool:
    return await _set_todo(max(0, index - 1), item)


class ParallelTask(BaseModel):
    tool: str = Field(..., description="Tool name to run")
    arguments: Dict[str, Any] = Field(
        default_factory=dict, description="Arguments for the tool"
    )


@tool(
    description="Run multiple tools in parallel. Input: list of {tool, arguments}. Returns list of results in order."
)
async def parallel_run(tasks: List[ParallelTask]) -> List[Any]:
    async def run_one(t: ParallelTask) -> Any:
        try:
            return await execute_tool(t.tool, dict(t.arguments))
        except Exception as e:
            return {"error": str(e)}

    # schedule concurrently
    coros = [run_one(t) for t in tasks]
    return await asyncio.gather(*coros, return_exceptions=False)


@tool(description="HTTP GET a URL and return text content. Optional timeout seconds.")
async def http_get(
    url: str, timeout: Optional[float] = 20.0, headers: Optional[Dict[str, str]] = None
) -> str:
    tout = timeout if timeout is not None else httpx.Timeout(5.0)
    async with httpx.AsyncClient(timeout=tout) as client:
        resp = await client.get(url, headers=headers or {})
        resp.raise_for_status()
        return str(resp.text)


@tool(description="Read a text file.")
def file_read(path: str, encoding: str = "utf-8") -> str:
    with open(path, "r", encoding=encoding) as f:
        return f.read()


@tool(description="Write text to a file (overwrites by default).")
def file_write(
    path: str, content: str, encoding: str = "utf-8", append: bool = False
) -> str:
    mode = "a" if append else "w"
    with open(path, mode, encoding=encoding) as f:
        f.write(content)
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
    if regex:
        compiled = re.compile(pattern)
    for p in paths:
        try:
            with open(p, "r", encoding=encoding) as f:
                data = f.read()
            if regex:
                new, n = compiled.subn(replacement, data)
            else:
                n = data.count(pattern)
                new = data.replace(pattern, replacement)
            if n:
                with open(p, "w", encoding=encoding) as f:
                    f.write(new)
                count += n
        except FileNotFoundError:
            continue
    return count
