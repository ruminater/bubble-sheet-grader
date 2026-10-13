"""Settings that belong to one installation, not to the code.

Read from bubblesheets.env beside this package (KEY=value lines, never
committed), and the environment overrides that file:

  BUBBLESHEETS_FOOTER      printed small at the foot of every sheet
                           (default: Bubble Sheet Creator)
  BUBBLESHEETS_GRADER_URL  where the page sends people to grade their scans
                           (default: the grader's own default address on this machine)
  BUBBLESHEETS_HOST        127.0.0.1 (the default) or 0.0.0.0 for the network
  BUBBLESHEETS_PORT        8773

The defaults name no institution and no server, so the code can be shared as it is.
"""

from __future__ import annotations

import os
import pathlib

ENV_FILE = pathlib.Path(__file__).resolve().parent.parent / "bubblesheets.env"


def _read() -> dict[str, str]:
    out = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("\"'")
    out.update({k: v for k, v in os.environ.items() if k.startswith("BUBBLESHEETS_")})
    return out


_s = _read()
FOOTER = _s.get("BUBBLESHEETS_FOOTER", "Bubble Sheet Creator")
GRADER_URL = _s.get("BUBBLESHEETS_GRADER_URL", "http://127.0.0.1:8765/")
HOST = _s.get("BUBBLESHEETS_HOST", "127.0.0.1")
PORT = int(_s.get("BUBBLESHEETS_PORT", "8773"))
