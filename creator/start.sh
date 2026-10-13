#!/bin/sh
# Bubble Sheet Creator.
#
#   ./start.sh               run in this Terminal window; Ctrl-C stops it
#   ./start.sh --background  start it detached (log in data/server.log)
#   ./start.sh --stop        stop a background server
#
# Loopback by default; put it behind whatever serves your network, or set
# BUBBLESHEETS_HOST=0.0.0.0 in bubblesheets.env. It holds nothing private.

cd "$(dirname "$0")" || exit 1
PORT="${BUBBLESHEETS_PORT:-8773}"
URL="http://127.0.0.1:$PORT"

answering() { curl -s -o /dev/null --max-time 1 "$URL/"; }

if [ "$1" = "--stop" ]; then
    PIDS=$(lsof -ti "tcp:$PORT" -sTCP:LISTEN)
    [ -n "$PIDS" ] || { echo "Nothing is listening on $PORT."; exit 0; }
    kill $PIDS
    n=0
    while lsof -ti "tcp:$PORT" -sTCP:LISTEN >/dev/null 2>&1; do
        n=$((n + 1)); [ "$n" -gt 40 ] && { echo "$PORT still held." >&2; exit 1; }
        sleep 0.25
    done
    echo "Stopped the Bubble Sheet Creator on $PORT."
    exit 0
fi

if answering; then
    echo "Already running. $URL"
    exit 0
fi

if [ ! -x .venv/bin/python ]; then
    echo "Making the virtual environment..."
    PY=$(command -v python3.14 || command -v python3)
    "$PY" -m venv .venv && .venv/bin/pip install -q -r requirements.txt || {
        echo "Could not make the virtual environment." >&2; exit 1; }
fi

mkdir -p data
export BUBBLESHEETS_PORT="$PORT"
if [ "$1" = "--background" ]; then
    nohup .venv/bin/python -m bubblesheets >> data/server.log 2>&1 &
    n=0
    until answering; do
        n=$((n + 1))
        [ "$n" -gt 40 ] && { echo "Did not answer in 20s. See $(pwd)/data/server.log" >&2; exit 1; }
        sleep 0.5
    done
    echo "Bubble Sheet Creator running. $URL"
    exit 0
fi

exec .venv/bin/python -m bubblesheets
