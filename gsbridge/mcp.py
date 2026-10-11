"""InterSpec MCP live-push client.

InterSpec (>= the 2026 builds, e.g. the 1.0.14 .deb) embeds an MCP/JSON-RPC
HTTP server with a ``load_spectrum_file`` tool that loads a spectrum directly
into a running session's display engine -- no re-launching the app, and no
file-model dedup (which otherwise serves stale in-memory copies of files whose
UUID was already seen).

This is *opt-in on InterSpec's side*: it ships disabled. To enable it, copy
``data/llm_config.xml`` from the InterSpec install into your InterSpec user
data directory (``~/.config/InterSpec`` on Linux), then inside the
``<McpServer>`` section set ``<Enabled>true</Enabled>`` and replace
``INVALID-BEARER-TOKEN`` with a token of your choice::

    <McpServer version="0">
      <Enabled>true</Enabled>
      <BearerToken>my-local-token</BearerToken>
    </McpServer>

Restart InterSpec. gsbridge auto-discovers the port from the listening socket
of the running ``interspec`` process (no fixed-port config needed -- note that
pinning HttpPortToServeOn via InterSpec_app_settings.json breaks startup on
some builds, so we do not recommend it).

The token is read from ``~/.config/gsbridge/mcp.json``::

    {"bearer_token": "my-local-token"}

or the environment variable ``GSBRIDGE_MCP_TOKEN``.

Only Python stdlib is used (urllib + json), so this adds no dependencies.
"""

from __future__ import annotations

import glob
import json
import os
import urllib.error
import urllib.request

DEFAULT_LANES = ("Foreground", "Background", "Secondary")


def discover_port() -> int | None:
    """Return the TCP port the running interspec process listens on, or None.

    Implemented per-platform with stdlib only:
      Linux   : /proc (exe link + socket inodes vs /proc/net/tcp LISTEN)
      macOS   : lsof -nP -iTCP -sTCP:LISTEN, matched on the process name
      Windows : netstat -ano (LISTEN ports + PIDs) + tasklist (PID -> image)

    The port is ephemeral (InterSpec picks a free one at startup), so this is
    re-run lazily on every new push session; an explicit ``port`` in
    ~/.config/gsbridge/mcp.json (or GSBRIDGE_MCP_PORT) always wins.
    """
    import platform
    system = platform.system()

    if system == "Linux":
        return _discover_port_linux()
    if system == "Darwin":
        return _discover_port_macos()
    if system == "Windows":
        return _discover_port_windows()
    return None


def _discover_port_linux() -> int | None:
    """Find pids whose exe is *interspec, then match their socket inodes
    against /proc/net/tcp LISTEN entries on 127.0.0.1."""
    inodes: set[str] = set()
    for pid_dir in glob.glob("/proc/[0-9]*"):
        try:
            exe = os.path.realpath(os.path.join(pid_dir, "exe"))
        except OSError:
            continue
        if os.path.basename(exe) != "interspec":
            continue
        for fd in glob.glob(os.path.join(pid_dir, "fd", "*")):
            try:
                link = os.readlink(fd)
            except OSError:
                continue
            if link.startswith("socket:["):
                inodes.add(link[8:-1])
    if not inodes:
        return None

    # 127.0.0.1 as little-endian hex is 0100007F; state 0A = LISTEN.
    for proc_net in ("/proc/net/tcp",):
        try:
            with open(proc_net) as fh:
                next(fh)  # header
                for line in fh:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    local, _remote, state, _proto, _uid, inode = (
                        parts[1], parts[2], parts[3], parts[4], parts[5], parts[9])
                    if state != "0A" or inode not in inodes:
                        continue
                    if not local.startswith("0100007F:"):
                        continue
                    return int(local.split(":")[1], 16)
        except OSError:
            pass
    return None


def _discover_port_macos() -> int | None:
    """lsof LISTEN sockets on 127.0.0.1 owned by a process named interspec."""
    import subprocess
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9 or parts[0].lower() != "interspec":
            continue
        # NAME column looks like 127.0.0.1:46633 (or *:port, [::1]:port)
        name = parts[8]
        if ":" not in name:
            continue
        host, _, port = name.rpartition(":")
        if host not in ("127.0.0.1", "localhost", "*", "[::1]", "::1"):
            continue
        try:
            return int(port)
        except ValueError:
            continue
    return None


def _discover_port_windows() -> int | None:
    """netstat LISTEN ports + owning PIDs, then tasklist PID -> interspec."""
    import subprocess
    try:
        net = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    ports_by_pid: dict[str, list[int]] = {}
    for line in net.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, state, pid = parts[1], parts[3], parts[4]
        if state.upper() != "LISTENING" or not pid.isdigit():
            continue
        host, _, port = local.rpartition(":")
        if host not in ("127.0.0.1", "[::1]", "::1"):
            continue
        try:
            ports_by_pid.setdefault(pid, []).append(int(port))
        except ValueError:
            continue
    if not ports_by_pid:
        return None
    try:
        task = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                              capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in task.splitlines():
        parts = [p.strip('"') for p in line.split('",')]
        if len(parts) < 2 or parts[0].lower() not in ("interspec.exe", "interspec"):
            continue
        if parts[1] in ports_by_pid:
            return min(ports_by_pid[parts[1]])
    return None


class McpPusher:
    """Minimal MCP-over-HTTP client for InterSpec's load_spectrum_file tool."""

    def __init__(self, bearer_token: str | None = None,
                 user_session: str | None = None, timeout: float = 4.0,
                 port: int | None = None):
        self.token = bearer_token if bearer_token is not None else _read_token()
        self.user_session = user_session
        self.timeout = timeout
        # explicit port wins over auto-discovery (config "port" or
        # GSBRIDGE_MCP_PORT); otherwise discovered per session
        self.fixed_port = port if port is not None else _read_port()
        self.port: int | None = None
        self._session_ready = False
        self._req_id = 0

    # -- low level -----------------------------------------------------
    def _rpc(self, method: str, params: dict):
        assert self.port is not None
        self._req_id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._req_id,
                           "method": method, "params": params}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/mcp-api",
                                     data=body,
                                     headers={"Content-Type": "application/json"})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def _ensure(self):
        if self._session_ready:
            return
        self.port = self.fixed_port or discover_port()
        if self.port is None:
            raise ConnectionError("interspec not running (no listening socket found)")
        reply = self._rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "gsbridge", "version": "0.2"}})
        if "error" in reply:
            raise ConnectionError(f"MCP initialize failed: {reply['error']}")
        self._session_ready = True

    # -- public ---------------------------------------------------------
    def load(self, path: str, lane: str = "Foreground",
             sample_numbers=None) -> dict:
        """Load *path* into the running InterSpec session's *lane*.

        Returns the tool's JSON result dict (includes success/totalCounts).
        Raises on transport or tool failure; a failed call invalidates the
        cached session so the next call re-discovers the port (handles
        InterSpec restarts between autosaves).

        sample_numbers: optional list of sample numbers to display, forwarded
        as the ``sampleNumbers`` argument. Passing it explicitly matters: if
        omitted, InterSpec's displayed-sample set stays empty for a freshly
        parsed file, and its "no energy calibration for the selected samples"
        warning fires even when the file carries a valid calibration (the check
        calls suggested_sum_energy_calibration(sample_numbers) which returns
        null on an empty set). See engine._push.
        """
        if lane not in DEFAULT_LANES:
            raise ValueError(f"lane must be one of {DEFAULT_LANES}")
        try:
            self._ensure()
            args: dict = {"path": os.path.abspath(path), "specType": lane}
            if sample_numbers:
                args["sampleNumbers"] = [int(s) for s in sample_numbers]
            if self.user_session:
                args["userSession"] = self.user_session
            reply = self._rpc("tools/call",
                              {"name": "load_spectrum_file", "arguments": args})
        except Exception:
            self._session_ready = False
            raise
        if "error" in reply:
            raise RuntimeError(f"load_spectrum_file error: {reply['error']}")
        content = reply.get("result", {}).get("content", [])
        text = next((c.get("text", "") for c in content if c.get("type") == "text"), "{}")
        result = json.loads(text)
        if not result.get("success"):
            raise RuntimeError(f"load_spectrum_file refused: {result}")
        return result


def _config_dir() -> str:
    """gsbridge's per-user config dir (platform-appropriate)."""
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA",
                                           os.path.expanduser("~")), "gsbridge")
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return os.path.join(xdg or os.path.expanduser("~/.config"), "gsbridge")


def _mcp_config() -> dict:
    try:
        with open(os.path.join(_config_dir(), "mcp.json")) as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_token() -> str:
    env = os.environ.get("GSBRIDGE_MCP_TOKEN")
    if env:
        return env
    return _mcp_config().get("bearer_token", "") or ""


def _read_port() -> int | None:
    """Optional explicit port override (env first, then mcp.json "port")."""
    env = os.environ.get("GSBRIDGE_MCP_PORT")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    try:
        return int(_mcp_config().get("port"))
    except (TypeError, ValueError):
        return None
