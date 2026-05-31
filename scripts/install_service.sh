#!/bin/bash
# install_service.sh - Install and start kb-web systemd service on Linux production server

# Ensure the script is run with sudo or as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo or as root:"
  echo "sudo ./install_service.sh"
  exit 1
fi

echo "Installing kb-web service..."

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_SERVICE="$SCRIPT_DIR/../kb-web.service"
DEST_SERVICE="/etc/systemd/system/kb-web.service"

# Check if source service file exists
if [ ! -f "$SRC_SERVICE" ]; then
  echo "Error: Source service file not found at $SRC_SERVICE."
  exit 1
fi

# Ensure virtual environment and executable exist
if [ ! -f "/srv/kb-web/.venv/bin/kb-web" ]; then
  echo "Virtual environment or kb-web executable not found at /srv/kb-web/.venv/bin/kb-web."
  if command -v uv &> /dev/null; then
    echo "Running 'uv sync' to set up the virtual environment..."
    (cd /srv/kb-web && uv sync)
  else
    echo "Error: 'uv' package manager is not installed or not in PATH."
    echo "Please install uv or manually set up the virtual environment at /srv/kb-web/.venv/"
    exit 1
  fi
fi

# Copy service file
cp "$SRC_SERVICE" "$DEST_SERVICE"
chmod 644 "$DEST_SERVICE"
echo "Copied service configuration to $DEST_SERVICE"

# Reload daemon
systemctl daemon-reload
echo "Systemd daemon reloaded"

# Enable service
systemctl enable kb-web.service
echo "Enabled kb-web service to start on boot"

# Start service
systemctl restart kb-web.service
echo "Started/Restarted kb-web service"

# Check status
systemctl status kb-web.service
