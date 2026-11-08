"""Create 230103033.zip (includes .git and .github). Run after `git tag final`.  python scripts/package_submission.py"""
import os
import zipfile

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".secrets", "dist", ".venv"}
out = "230103033.zip"
if os.path.exists(out):
    os.remove(out)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for d, dirs, files in os.walk("."):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            p = os.path.join(d, f)
            if p.endswith((".safetensors", ".bin", ".pt")) or f == out:
                continue
            z.write(p, p[2:])
print("wrote", out, os.path.getsize(out), "bytes")
