"""Token generation + one-time InterSpec MCP configuration (shared by CLI/GUI).

One token is shared by both sides of the bridge:

* InterSpec needs it in its user ``llm_config.xml`` under
  ``<McpServer><BearerToken>`` (with ``<Enabled>true</Enabled>``), either via
  its Tools -> LLM Assistant GUI or written here directly.
* mcabridge keeps it in ``~/.config/mcabridge/mcp.json`` (Windows:
  ``%APPDATA%\\mcabridge\\mcp.json``, macOS:
  ``~/Library/Application Support/mcabridge/mcp.json``).

Functions here are stdlib-only and safe to call from the GUI; the CLI exposes
them as ``--gen-token``, ``--set-token`` and ``--setup-mcp``.
"""

from __future__ import annotations

import json
import secrets
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .mcp import _config_dir, _load_json

DEFAULT_TOKEN_BYTES = 32


def generate_token(nbytes: int = DEFAULT_TOKEN_BYTES) -> str:
    """Cryptographically random hex token (same format the docs suggest)."""
    return secrets.token_hex(nbytes)


def bridge_config_path() -> Path:
    """Path of mcabridge's mcp.json (per-user, platform-appropriate)."""
    return Path(_config_dir()) / "mcp.json"


def save_bridge_token(token: str, port: int | None = None) -> Path:
    """Store *token* for the bridge in mcp.json (existing file backed up to
    .bak; a previously configured explicit ``port`` override is preserved)."""
    token = token.strip()
    if not token:
        raise ValueError("token is empty")
    cfg_path = bridge_config_path()
    cfg = _load_json(str(cfg_path))
    cfg["bearer_token"] = token
    if port is not None:
        cfg["port"] = int(port)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    if cfg_path.exists():
        shutil.copy2(cfg_path, cfg_path.with_suffix(".json.bak"))
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    return cfg_path


def read_bridge_token() -> str:
    """Current saved token ("" when none). Env var not consulted here — this
    is for the GUI's "what's saved" display."""
    return str(_load_json(str(bridge_config_path())).get("bearer_token", ""))


# ---- InterSpec side --------------------------------------------------------

def interspec_user_dir() -> Path:
    """Electron userData dir (matches app.getPath('userData'))."""
    import os
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "InterSpec"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "InterSpec"
    return Path(os.environ.get("XDG_CONFIG_HOME",
                               str(Path.home() / ".config"))) / "InterSpec"


def interspec_install_data() -> Path | None:
    """Locate the shipped data/llm_config.xml next to an installed InterSpec."""
    import os
    candidates = [
        "/opt/InterSpec/resources/app/data",                      # Linux .deb
        str(Path("/Applications/InterSpec.app/Contents/Resources/app/data")),  # macOS
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                     "InterSpec/resources/app/data"),             # Windows
    ]
    for c in candidates:
        if (Path(c) / "llm_config.xml").is_file():
            return Path(c)
    return None


def enable_mcp(xml_text: str, token: str) -> str:
    """Return *xml_text* with McpServer enabled and BearerToken set."""
    root = ET.fromstring(xml_text)
    mcp = root.find("McpServer")
    if mcp is None:
        raise RuntimeError(
            "This llm_config.xml has no <McpServer> section - your InterSpec "
            "build predates the MCP API; use mcabridge --push-mode launch "
            "instead.")
    en = mcp.find("Enabled")
    if en is None:
        en = ET.SubElement(mcp, "Enabled")
    en.text = "true"
    tok = mcp.find("BearerToken")
    if tok is None:
        tok = ET.SubElement(mcp, "BearerToken")
    tok.text = token
    ET.indent(root, space="  ")  # py3.9+; cosmetic only
    return ET.tostring(root, encoding="unicode")


def configure_interspec(token: str, print_only: bool = False) -> list[str]:
    """Enable MCP + set *token* in InterSpec's user llm_config.xml (copied from
    the install template when absent; existing file backed up to .xml.bak).

    Returns human-readable log lines. Raises RuntimeError when nothing usable
    is found. NOTE: run while InterSpec is CLOSED — a running instance rewrites
    its config on exit and would clobber this.
    """
    token = token.strip()
    if not token:
        raise ValueError("token is empty")
    user_dir = interspec_user_dir()
    target = user_dir / "llm_config.xml"
    src = interspec_install_data()

    if target.is_file():
        base = target.read_text()
        source_note = f"updating existing {target}"
    elif src is not None:
        base = (src / "llm_config.xml").read_text()
        source_note = f"from install template {src}/llm_config.xml"
    else:
        raise RuntimeError(
            f"no InterSpec user config at {target} and no install template "
            "found. Install InterSpec (.deb/.dmg/zip) first, or enable the MCP "
            "server via Tools -> LLM Assistant inside InterSpec and just save "
            "the token for the bridge (--set-token).")

    updated = enable_mcp(base, token)
    log = [f"InterSpec config  : {target}", f"source            : {source_note}"]
    if print_only:
        return log + ["(print-only: nothing written)"]

    user_dir.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        shutil.copy2(target, target.with_suffix(".xml.bak"))
    target.write_text(updated)
    return log + [f"written           : {target} (previous version saved as .xml.bak)"]


def setup_mcp(token: str | None = None, print_only: bool = False) -> tuple[str, list[str]]:
    """Full one-shot setup: generate token if needed, configure InterSpec's
    llm_config.xml AND save the bridge token. Returns (token, log lines)."""
    token = (token or generate_token()).strip()
    log = configure_interspec(token, print_only=print_only)
    cfg_path = save_bridge_token(token)
    log.append(f"bridge token      : {cfg_path}")
    if not print_only:
        log.append("")
        log.append("Done. Restart InterSpec (or re-save its settings via "
                   "Tools -> LLM Assistant), then run:  mcabridge --check")
    return token, log
