from textual_cli_agent.tools import tool


@tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool(description="Echo a string N times")
def echo(text: str, times: int = 1) -> str:
    return " ".join([text] * times)
