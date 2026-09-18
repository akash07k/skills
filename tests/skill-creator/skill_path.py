"""Make the skill-creator scripts importable from the repository-level tests."""

import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "skill-creator"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))
