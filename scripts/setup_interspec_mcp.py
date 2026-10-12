#!/usr/bin/env python3
"""One-shot InterSpec MCP setup for mcabridge (config only — no InterSpec code
changes).

Enables InterSpec's built-in MCP API by placing an llm_config.xml override in
InterSpec's per-user data directory, and stores the matching bearer token for
mcabridge. Safe to re-run; existing files are backed up next time you run it.

Usage:
    python scripts/setup_interspec_mcp.py [--token YOURTOKEN] [--print-only]

Or skip this script entirely in InterSpec's GUI:
    Tools -> LLM Assistant -> (gear/settings) -> check "MCP Server", set a
    bearer token, save. Then just create ~/.config/mcabridge/mcp.json with
    {"bearer_token": "<same token>"}.
"""

import argparse
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_TOKEN = "gsbri…oken"


def interspec_user_dir() -> Path:
    """Electron userData dir (matches app.getPath('userData'))."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "InterSpec"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "InterSpec"
    return Path(os.environ.get("XDG_CONFIG_HOME",
                               str(Path.home() / ".config"))) / "InterSpec"


def interspec_install_data() -> Path | None:
    """Locate the shipped data/llm_config.xml next to an installed InterSpec."""
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
    root = ET.fromstring(xml_text)
    mcp = root.find("McpServer")
    if mcp is None:
        raise SystemExit("This llm_config.xml has no <McpServer> section - your "
                         "InterSpec build predates the MCP API; use mcabridge "
                         "--push-mode launch instead.")
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--token", default=DEFAULT_TOKEN)
    ap.add_argument("--print-only", action="store_true",
                    help="show what would change; write nothing")
    args = ap.parse_args()

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
        print(f"ERROR: no user config at {target} and no InterSpec install "
              "template found.\nInstall InterSpec (.deb/.dmg) first, or copy "
              "data/llm_config.xml from its resources/app directory to the "
              f"path above.", file=sys.stderr)
        return 1

    updated = enable_mcp(base, args.token)

    mcabridge_cfg = (Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
                    if os.name != "nt" else Path(os.environ["APPDATA"])) / "mcabridge" / "mcp.json"

    print(f"InterSpec user dir : {user_dir}")
    print(f"source             : {source_note}")
    print(f"will write         : {target}")
    print(f"                   : {mcabridge_cfg}")
    print(f"bearer token       : {args.token}")
    if args.print_only:
        return 0

    user_dir.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        shutil.copy2(target, target.with_suffix(".xml.bak"))
    target.write_text(updated)

    mcabridge_cfg.parent.mkdir(parents=True, exist_ok=True)
    if mcabridge_cfg.exists():
        shutil.copy2(mcabridge_cfg, mcabridge_cfg.with_suffix(".json.bak"))
    mcabridge_cfg.write_text(json.dumps({"bearer_token": args.token}, indent=2) + "\n")

    print("\nDone. Restart InterSpec (or re-save its settings via Tools -> LLM "
          "Assistant), then run:\n    mcabridge --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
