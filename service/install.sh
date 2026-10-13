#!/bin/bash
# Run the grader in the background on this Mac, from login, restarting if it
# stops. Run once from the scantron folder:  ./service/install.sh
# Undo with ./service/uninstall.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
LABEL=local.scantron-grader
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/scantron.log"

if [ ! -f scantron.env ]; then
  echo "No scantron.env yet. Copy scantron.env.example to scantron.env and set a password first."
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Setting up Python packages..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$DIR/.venv/bin/python</string><string>-m</string><string>scantron</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict><key>SCANTRON_BROWSER</key><string>0</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 3
PORT=$(grep -E '^SCANTRON_PORT=' scantron.env | cut -d= -f2 || true); PORT=${PORT:-8765}
if curl -s -o /dev/null "http://127.0.0.1:$PORT/login"; then
  IP=$(ipconfig getifaddr en0 || ipconfig getifaddr en1 || echo "this-mac's-address")
  echo "Running. Others on the network can use: http://$IP:$PORT/"
  echo "Log: $LOG"
else
  echo "It did not start. The last lines of $LOG:"; tail -n 20 "$LOG" 2>/dev/null || echo "(no log yet)"
  exit 1
fi
