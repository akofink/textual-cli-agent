import os
import sys

# Ensure repository root is on sys.path when running under pre-commit
REPO_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
