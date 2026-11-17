"""An ms365 MCP client (@softeria/ms-365-mcp-server) over stdio: one server process for the whole run, tool calls over
JSON-RPC. The Microsoft 365 sign-in belongs to the server (its token cache); the plugin neither sees nor stores tokens:
sign in once with `npx -y @softeria/ms-365-mcp-server@<version> --org-mode --login` (README)."""
import glob
import json
import os
import shutil
import subprocess
import tempfile

SERVER = ["-y", "@softeria/ms-365-mcp-server@0.158.0", "--org-mode"]


def node_env():
    """PATH with node: under launchd it is often missing (fnm, nvm, keg-only Homebrew), so we look for it ourselves."""
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
        self.err = tempfile.TemporaryFile("w+")   # the server logs audit noise to stderr: read only on a failure
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
                raise OSError("ms365: server closed")   # the tail of the server stderr stays out of the error: it goes to the channel
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
