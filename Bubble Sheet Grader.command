#!/bin/bash
# Double-click in Finder to start the grader. First run sets up its own Python
# environment, which takes a minute; later runs start in a few seconds.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || {
    echo "Setup failed. Is Python 3 installed? (python3 --version)"; read -r; exit 1; }
fi
exec .venv/bin/python -m bubblegrader
