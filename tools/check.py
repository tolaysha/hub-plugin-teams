"""Existing offline plugin gate; no collector, account or real send."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
if env.get("HUB_CORE"):
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [env["HUB_CORE"], env.get("PYTHONPATH")]))
commands = [[sys.executable, "-m", "unittest", "discover", "-s", "tests"]]
commands += [["node", str(test.relative_to(root)), "web/main.js"] for test in sorted((root / "tests").glob("*.test.mjs"))]
for command in commands:
    subprocess.run(command, cwd=root, env=env, check=True)
