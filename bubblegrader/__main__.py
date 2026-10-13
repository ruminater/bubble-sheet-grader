"""python -m bubblegrader: start the grader.

Settings come from grader.env beside this package (KEY=value lines), and
the environment overrides that file:

  GRADER_HOST      127.0.0.1 (this machine only, the default) or 0.0.0.0 (the network)
  GRADER_PORT      8765
  GRADER_PASSWORD  required whenever the host is not this machine only
  GRADER_HTTPS     1 when people reach it over https (a Cloudflare Tunnel, say)
  GRADER_BROWSER   0 to skip opening a browser, as the background service does
"""

import os
import pathlib
import sys
import threading
import webbrowser

from waitress import serve

from .app import app, configure

ENV_FILE = pathlib.Path(__file__).resolve().parent.parent / "grader.env"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def settings() -> dict[str, str]:
    out = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("\"'")
    out.update({k: v for k, v in os.environ.items() if k.startswith("GRADER_")})
    return out


def main() -> None:
    s = settings()
    host = s.get("GRADER_HOST", "127.0.0.1")
    port = int(s.get("GRADER_PORT", "8765"))
    password = s.get("GRADER_PASSWORD", "")
    if host not in LOOPBACK and len(password) < 10:
        sys.exit(
            f"Refusing to serve on {host} without a password of 10+ characters: these pages "
            f"carry student names and scores. Set GRADER_PASSWORD in {ENV_FILE}."
        )
    configure(password=password, https=s.get("GRADER_HTTPS") == "1")

    shown = "127.0.0.1" if host in LOOPBACK or host == "0.0.0.0" else host
    print(f"Bubble Sheet Grader on http://{shown}:{port}/"
          + (" and this machine's network address" if host == "0.0.0.0" else "")
          + (" (password required)" if password else "") + "  Ctrl+C to stop")
    if s.get("GRADER_BROWSER", "1") != "0":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    # Grading a class set takes a while; threads keep one person's upload from
    # stalling everyone else's pages.
    serve(app, host=host, port=port, threads=8, channel_timeout=300,
          max_request_body_size=app.config["MAX_CONTENT_LENGTH"], ident=None)


if __name__ == "__main__":
    main()
