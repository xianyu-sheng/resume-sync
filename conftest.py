"""
Pytest configuration: ensures src/ is importable and sets a writable
basetemp to avoid Windows temp-directory permission issues.
"""

import sys
from pathlib import Path

# Add the project root (parent of this file) to sys.path so that
# "from src.checker import Checker" works from tests/.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
