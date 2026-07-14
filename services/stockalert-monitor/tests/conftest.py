import os
import sys

# Make top-level modules importable when running pytest from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
