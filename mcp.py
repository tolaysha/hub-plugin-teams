"""Клиент ms365 MCP (@softeria/ms-365-mcp-server) по stdio: один процесс сервера на всё время, вызовы инструментов
JSON-RPC. Вход в Microsoft 365 — у сервера (его кэш токенов), плагин токенов не видит и не хранит: войти один раз —
`npx -y @softeria/ms-365-mcp-server@<версия> --org-mode --login` (README)."""
import glob
import json
import os
import shutil
import subprocess
import tempfile

SERVER = ["-y", "@softeria/ms-365-mcp-server@0.158.0", "--org-mode"]


def node_env():
    """PATH с node: под launchd его часто нет (fnm, nvm, keg-only Homebrew) — ищем сами."""
    env = dict(os.environ)
    if not shutil.which("node", path=env.get("PATH")):
        for pat in ("/opt/homebrew/Cellar/node@*/*/bin", "/opt/homebrew/bin", "/usr/local/bin",
                    os.path.expanduser("~/.local/share/fnm/aliases/default/bin"),
                    os.path.expanduser("~/.nvm/versions/node/*/bin")):
            for d in sorted(glob.glob(pat), reverse=True):
                if os.path.exists(os.path.join(d, "node")):
                    env["PATH"] = d + os.pathsep + env.get("PATH", "")
                    return env
    return env


class Mcp:
    def __init__(self):
        self.err = tempfile.TemporaryFile("w+")   # сервер шумит аудитом в stderr: читаем только при сбое
        env = node_env()
        npx = shutil.which("npx", path=env.get("PATH")) or "npx"
        self.p = subprocess.Popen([npx, *SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.err, text=True, env=env)
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "hub-teams", "version": "1"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()

    def rpc(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise OSError("ms365: сервер закрылся")   # хвост stderr сервера в ошибку не берём: он уходит в канал
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("id") == self.n:
                if "error" in m:
                    raise OSError(f"ms365: {str((m['error'] or {}).get('message') or m['error'])[:200]}")
                return m["result"]

    def call(self, tool, args):
        r = self.rpc("tools/call", {"name": tool, "arguments": args})
        text = "".join(c.get("text", "") for c in r.get("content", []))
        if r.get("isError"):
            raise OSError(f"ms365 {tool}: {text[:200]}")
        return json.loads(text)

    def close(self):
        self.p.kill()
        self.p.wait()
        self.err.close()
