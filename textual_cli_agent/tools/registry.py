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
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
)

from pydantic import BaseModel

from textual_cli_agent.providers.base import ToolSpec

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
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        model_t = cast(type[BaseModel], ann)
        schema = cast(Dict[str, Any], model_t.model_json_schema())
        return schema

    origin = get_origin(ann)
    if origin is list or origin is List:
        (arg,) = get_args(ann) if get_args(ann) else (str,)
        return {"type": "array", "items": _annotation_to_schema(arg)}
    if origin is dict or origin is Dict:
        return {"type": "object"}

    mapping = {int: "integer", float: "number", str: "string", bool: "boolean"}
    if ann in mapping:
        return {"type": mapping[ann]}

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
    registered = _TOOL_REGISTRY[name]
    if registered.is_async:
        return await registered.func(**arguments)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: registered.func(**arguments))


def load_tools_from_modules(modules: List[str]) -> List[RegisteredTool]:
    for mod in modules:
        importlib.import_module(mod)
    return list(_TOOL_REGISTRY.values())
