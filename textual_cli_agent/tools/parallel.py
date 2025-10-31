from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from .registry import execute_tool, tool


class ParallelTask(BaseModel):
    tool: str = Field(..., description="Tool name to run")
    arguments: Dict[str, Any] = Field(
        default_factory=dict, description="Arguments for the tool"
    )


@tool(
    description="Run multiple tools in parallel. Input: list of {tool, arguments}. Returns list of results in order."
)
async def parallel_run(tasks: List[ParallelTask]) -> List[Any]:
    async def run_one(task: ParallelTask) -> Any:
        try:
            return await execute_tool(task.tool, dict(task.arguments))
        except Exception as exc:
            return {"error": str(exc)}

    coros = [run_one(task) for task in tasks]
    return await asyncio.gather(*coros, return_exceptions=False)
