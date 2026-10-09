#!/bin/sh
# Процесс плагина: нужен Python 3.12+ (код хаба в PYTHONPATH). Под launchd в PATH часто только системный python3 3.9 —
# ищем подходящий сами.
for p in "$HUB_PYTHON" python3.14 python3.13 python3.12 "$HOME/.local/bin/python3.12" /opt/homebrew/bin/python3 python3; do
  [ -n "$p" ] || continue
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    exec "$p" main.py
  fi
done
echo "teams: нужен Python 3.12 или новее" >&2
exit 1
