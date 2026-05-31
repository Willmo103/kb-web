#!/bin/bash
# manage.sh - Manage the kb-web production systemd service

show_help() {
  echo "Usage: ./manage.sh [start|stop|restart|status|logs]"
  echo "Commands:"
  echo "  start    - Start the kb-web service"
  echo "  stop     - Stop the kb-web service"
  echo "  restart  - Restart the kb-web service"
  echo "  status   - Check the running status of the service"
  echo "  logs     - Stream live systemd journal logs"
}

if [ -z "$1" ]; then
  show_help
  exit 1
fi

case "$1" in
  start)
    echo "Starting kb-web service..."
    sudo systemctl start kb-web.service
    ;;
  stop)
    echo "Stopping kb-web service..."
    sudo systemctl stop kb-web.service
    ;;
  restart)
    echo "Restarting kb-web service..."
    sudo systemctl restart kb-web.service
    ;;
  status)
    systemctl status kb-web.service
    ;;
  logs)
    echo "Streaming logs for kb-web. Press Ctrl+C to exit."
    journalctl -u kb-web.service -f
    ;;
  *)
    show_help
    exit 1
    ;;
esac
