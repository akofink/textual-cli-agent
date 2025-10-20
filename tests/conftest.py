import os
import sys

import pytest

# Ensure repository root is on sys.path when running under pre-commit
REPO_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


@pytest.fixture(autouse=True)
def _isolate_provider_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent accidental use of real provider credentials during tests."""
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "API_KEY"):
        monkeypatch.delenv(key, raising=False)
