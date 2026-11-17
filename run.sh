#!/bin/sh
# The plugin process: needs Python 3.12+ (the hub code on PYTHONPATH). Under launchd PATH often has only the system
# python3 3.9, so we look for a suitable one ourselves.
for p in "$HUB_PYTHON" python3.14 python3.13 python3.12 "$HOME/.local/bin/python3.12" /opt/homebrew/bin/python3 python3; do
  [ -n "$p" ] || continue
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    exec "$p" main.py
  fi
done
echo "teams: Python 3.12 or newer is needed" >&2
exit 1
