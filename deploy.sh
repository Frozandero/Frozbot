#!/bin/bash

# FrozBot Deployment Script
# Usage: ./deploy.sh [start|stop|restart|status|logs|refresh]

BOT_NAME="frozbot"
SERVICE_FILE="frozbot.service"
SERVICE_NAME="${BOT_NAME}.service"

case "$1" in
    start)
        echo "Starting FrozBot..."
        sudo systemctl start $SERVICE_NAME
        sudo systemctl enable $SERVICE_NAME
        echo "FrozBot started and enabled!"
        ;;
    stop)
        echo "Stopping FrozBot..."
        sudo systemctl stop $SERVICE_NAME
        sudo systemctl disable $SERVICE_NAME
        echo "FrozBot stopped and disabled!"
        ;;
    restart)
        echo "Restarting FrozBot..."
        sudo systemctl restart $SERVICE_NAME
        echo "FrozBot restarted!"
        ;;
    status)
        echo "FrozBot Status:"
        sudo systemctl status $SERVICE_NAME
        ;;
    logs)
        echo "FrozBot Logs (last 50 lines):"
        sudo journalctl -u $SERVICE_NAME -n 50 -f
        ;;
    refresh)
        echo "Refreshing commands via Discord refresh command..."
        echo "Use /refresh in your Discord server to refresh commands immediately."
        echo "Or restart the bot to sync changes: ./deploy.sh restart"
        ;;
    install)
        echo "Installing FrozBot service..."
        if [ ! -f "$SERVICE_FILE" ]; then
            echo "Error: $SERVICE_FILE not found!"
            exit 1
        fi
        
        # Copy service file to systemd directory
        sudo cp "$SERVICE_FILE" "/etc/systemd/system/$SERVICE_NAME"
        
        # Reload systemd
        sudo systemctl daemon-reload
        
        echo "Service installed! Edit the service file to set correct paths:"
        echo "sudo nano /etc/systemd/system/$SERVICE_NAME"
        echo ""
        echo "Then start with: ./deploy.sh start"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|refresh|install}"
        echo ""
        echo "Commands:"
        echo "  start    - Start and enable the bot service"
        echo "  stop     - Stop and disable the bot service"
        echo "  restart  - Restart the bot service"
        echo "  status   - Show bot service status"
        echo "  logs     - Show bot logs (follow mode)"
        echo "  refresh  - Instructions for refreshing commands"
        echo "  install  - Install the systemd service"
        exit 1
        ;;
esac
