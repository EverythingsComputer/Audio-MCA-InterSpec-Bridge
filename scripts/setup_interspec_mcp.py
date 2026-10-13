#!/usr/bin/env python3
"""One-shot InterSpec MCP setup for mcabridge (config only — no InterSpec code
changes).

Thin wrapper around mcabridge.setup, which the GUI ("MCP token…" button) and
the CLI (`mcabridge --setup-mcp / --gen-token / --set-token`) also use.

Usage:
    python scripts/setup_interspec_mcp.py [--token YOURTOKEN] [--print-only]

Or inside mcabridge's GUI: click "MCP token…" -> Generate -> Configure both.
Or in InterSpec's own GUI: Tools -> LLM Assistant -> check "MCP Server", set a
bearer token, save; then `mcabridge --set-token <same token>`.
"""

import argparse
import sys
from pathlib import Path

# allow running from a source checkout without installing mcabridge first
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcabridge import setup as msetup


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--token", default=None,
                    help="bearer token (default: generate a random one)")
    ap.add_argument("--print-only", action="store_true",
                    help="show what would change; write nothing")
    args = ap.parse_args()

    try:
        token, log = msetup.setup_mcp(token=args.token,
                                      print_only=args.print_only)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    for line in log:
        print(line)
    if not args.print_only:
        print(f"bearer token       : {token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
