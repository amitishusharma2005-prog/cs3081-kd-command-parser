import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SKIP_MODEL_LOAD", "1")
os.environ.setdefault("SCHEMA_PATH", os.path.join(ROOT, "data", "schema.json"))
for sub in ("", "worker", "training"):
    sys.path.insert(0, os.path.join(ROOT, sub))
