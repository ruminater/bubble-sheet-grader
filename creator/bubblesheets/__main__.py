"""python -m bubblesheets: start the Bubble Sheet Creator. Settings: see settings.py."""

from waitress import serve

from . import settings
from .app import app


def main() -> None:
    host, port = settings.HOST, settings.PORT
    print(f"Bubble Sheet Creator on http://{host}:{port}/  Ctrl+C to stop")
    serve(app, host=host, port=port, threads=4, ident=None)


if __name__ == "__main__":
    main()
