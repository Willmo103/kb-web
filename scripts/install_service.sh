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
SRC_SERVICE="/srv/kb-web/kb-web.service"
DEST_SERVICE="/etc/systemd/system/kb-web.service"

# Check if source service file exists
if [ ! -f "$SRC_SERVICE" ]; then
  echo "Error: Source service file not found at $SRC_SERVICE."
  echo "Ensure the repository is cloned at /srv/kb-web/ and this script is run from there."
  exit 1
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
