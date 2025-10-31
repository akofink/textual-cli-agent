from __future__ import annotations

from typing import Dict, Optional

import httpx

from .registry import tool


@tool(description="HTTP GET a URL and return text content. Optional timeout seconds.")
async def http_get(
    url: str, timeout: Optional[float] = 20.0, headers: Optional[Dict[str, str]] = None
) -> str:
    effective_timeout = timeout if timeout is not None else httpx.Timeout(5.0)
    async with httpx.AsyncClient(timeout=effective_timeout) as client:
        response = await client.get(url, headers=headers or {})
        response.raise_for_status()
        return str(response.text)
