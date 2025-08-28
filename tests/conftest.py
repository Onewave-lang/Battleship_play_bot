import os
import sys
from pathlib import Path

# Disable artificial delays during tests for faster execution
os.environ.setdefault("STATE_DELAY", "0")

sys.path.append(str(Path(__file__).resolve().parents[1]))
