#!/bin/bash
# Stop the background grader and remove it from login.
LABEL=local.bubble-sheet-grader
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Stopped." || echo "It was not running."
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
