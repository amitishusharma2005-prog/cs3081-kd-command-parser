"""Run AFTER you replaced 230103033.pdf with your handwritten scan:
commit it, move the `final` tag to that commit, push, re-check and write 230103033.zip.
    python3 scripts/seal_submission.py"""
import subprocess
import sys

PY = sys.executable
for cmd in (["git", "add", "-A"], ["git", "commit", "-m", "Add handwritten reflection scan"], ["git", "tag", "-f", "final"],
            ["git", "push", "origin", "main"], ["git", "push", "-f", "origin", "final"]):
    subprocess.run(cmd, check=False)
rc = subprocess.run([PY, "scripts/check_submission.py"]).returncode
subprocess.run([PY, "scripts/package_submission.py"], check=True)
print("\nDONE. Submit ONLY 230103033.zip" + ("" if rc == 0 else "  (some checks FAILED above)"))
