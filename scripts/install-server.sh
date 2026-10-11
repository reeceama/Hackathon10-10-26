#!/bin/sh
# Starts the Referee server, the Word helper and the Word add-in's HTTPS server whenever you log
# in to your Mac, and restarts them if they stop. The first time the helper reads Word, macOS asks
# whether it may control Microsoft Word: allow it.
# Run once from the repository folder: sh scripts/install-server.sh
# To remove: for n in server word helper; do launchctl bootout gui/$(id -u)/com.referee.$n; rm ~/Library/LaunchAgents/com.referee.$n.plist; done
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$HOME/Library/Logs/Referee"
mkdir -p "$HOME/Library/LaunchAgents" "$LOGS"

# install NAME WORKING_DIRECTORY ARGUMENTS...
install() {
  NAME="$1"; DIR="$2"; shift 2
  PLIST="$HOME/Library/LaunchAgents/com.referee.$NAME.plist"
  ARGS=""
  for a in "$@"; do ARGS="$ARGS<string>$a</string>"; done
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.referee.$NAME</string>
  <key>ProgramArguments</key><array>$ARGS</array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOGS/$NAME.log</string>
  <key>StandardErrorPath</key><string>$LOGS/$NAME.log</string>
</dict>
</plist>
PLIST
  launchctl bootout "gui/$(id -u)/com.referee.$NAME" 2>/dev/null && sleep 2 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
}

install server "$REPO/server" "$REPO/.venv/bin/python" -m uvicorn main:app --port 8000
install word "$REPO/word-addin" "$REPO/.venv/bin/python" server.py
install helper "$REPO/word-helper" "$REPO/.venv/bin/python" helper.py
echo "Referee installed. Logs: $LOGS"
