#!/bin/bash

# FrozBot Deployment Script
# Usage: ./deploy.sh [bootstrap|install|start|stop|restart|status|logs|refresh]

BOT_NAME="frozbot"
SERVICE_NAME="${BOT_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="${FROZBOT_BOT_DIR:-$SCRIPT_DIR}"
RUN_USER="${FROZBOT_SERVICE_USER:-$(id -un)}"
BOOTSTRAP_USER="${FROZBOT_BOOTSTRAP_USER:-frozbot}"
BOOTSTRAP_DIR="${FROZBOT_BOOTSTRAP_DIR:-/opt/frozbot}"

detect_python() {
    if [ -n "${FROZBOT_PYTHON:-}" ]; then
        echo "$FROZBOT_PYTHON"
        return
    fi

    for candidate in \
        "$BOT_DIR/.venv/bin/python" \
        "$BOT_DIR/venv/bin/python" \
        "$BOT_DIR/env/bin/python"
    do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done

    command -v python3 || command -v python || true
}

PYTHON_BIN="$(detect_python)"
VENV_DIR="${FROZBOT_VENV_DIR:-}"

if [ -z "$VENV_DIR" ] && [ -n "$PYTHON_BIN" ]; then
    case "$PYTHON_BIN" in
        "$BOT_DIR"/*/bin/python*)
            VENV_DIR="$(dirname "$(dirname "$PYTHON_BIN")")"
            ;;
    esac
fi

if [ -n "$VENV_DIR" ]; then
    PATH_PREFIX="$VENV_DIR/bin"
elif [ -n "$PYTHON_BIN" ]; then
    PATH_PREFIX="$(dirname "$PYTHON_BIN")"
else
    PATH_PREFIX="/usr/bin"
fi

install_service() {
    echo "Installing FrozBot service..."
    if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
        echo "Error: Python executable not found."
        echo "Create a virtual environment and install dependencies first:"
        echo "  python3 -m venv .venv"
        echo "  . .venv/bin/activate"
        echo "  pip install -r requirements.txt"
        echo ""
        echo "Or set FROZBOT_PYTHON=/path/to/python before running install."
        exit 1
    fi

    # Generate a systemd unit for this checkout instead of requiring manual edits.
    sudo tee "/etc/systemd/system/$SERVICE_NAME" > /dev/null <<EOF
[Unit]
Description=FrozBot Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$BOT_DIR
EnvironmentFile=-$BOT_DIR/.env
Environment=PATH=$PATH_PREFIX:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$PYTHON_BIN $BOT_DIR/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload

    echo "Service installed for:"
    echo "  User: $RUN_USER"
    echo "  Directory: $BOT_DIR"
    echo "  Python: $PYTHON_BIN"
    if [ -n "$VENV_DIR" ]; then
        echo "  Virtualenv: $VENV_DIR"
    fi
    echo ""
    echo "Then start with: ./deploy.sh start"
}

case "$1" in
    bootstrap)
        if [ "$(id -u)" -ne 0 ]; then
            echo "Error: bootstrap must be run as root."
            echo "Use sudo ./deploy.sh bootstrap"
            exit 1
        fi

        echo "Bootstrapping FrozBot into $BOOTSTRAP_DIR as user $BOOTSTRAP_USER..."
        apt update
        apt install -y python3-venv python3-pip ffmpeg rsync

        if ! id "$BOOTSTRAP_USER" >/dev/null 2>&1; then
            useradd --system --create-home --home-dir "$BOOTSTRAP_DIR" --shell /usr/sbin/nologin "$BOOTSTRAP_USER"
        fi

        mkdir -p "$BOOTSTRAP_DIR"
        rsync -a \
            --exclude ".git/" \
            --exclude ".venv/" \
            --exclude "venv/" \
            --exclude "env/" \
            --exclude "__pycache__/" \
            --exclude "*.pyc" \
            "$SCRIPT_DIR/" "$BOOTSTRAP_DIR/"

        chown -R "$BOOTSTRAP_USER:$BOOTSTRAP_USER" "$BOOTSTRAP_DIR"
        if [ -f "$BOOTSTRAP_DIR/.env" ]; then
            chmod 600 "$BOOTSTRAP_DIR/.env"
        fi

        sudo -u "$BOOTSTRAP_USER" python3 -m venv "$BOOTSTRAP_DIR/.venv"
        sudo -u "$BOOTSTRAP_USER" "$BOOTSTRAP_DIR/.venv/bin/python" -m pip install -r "$BOOTSTRAP_DIR/requirements.txt"

        FROZBOT_BOT_DIR="$BOOTSTRAP_DIR" \
        FROZBOT_SERVICE_USER="$BOOTSTRAP_USER" \
        FROZBOT_VENV_DIR="$BOOTSTRAP_DIR/.venv" \
        FROZBOT_PYTHON="$BOOTSTRAP_DIR/.venv/bin/python" \
            "$BOOTSTRAP_DIR/deploy.sh" install

        systemctl enable --now "$SERVICE_NAME"
        echo "FrozBot bootstrapped and started."
        echo "Check status with: systemctl status $SERVICE_NAME"
        echo "View logs with: journalctl -u $SERVICE_NAME -n 50 -f"
        ;;
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
        install_service
        ;;
    *)
        echo "Usage: $0 {bootstrap|install|start|stop|restart|status|logs|refresh}"
        echo ""
        echo "Commands:"
        echo "  bootstrap - Create service user, install to /opt/frozbot, and start"
        echo "  install   - Install the systemd service for this checkout"
        echo "  start    - Start and enable the bot service"
        echo "  stop     - Stop and disable the bot service"
        echo "  restart  - Restart the bot service"
        echo "  status   - Show bot service status"
        echo "  logs     - Show bot logs (follow mode)"
        echo "  refresh  - Instructions for refreshing commands"
        exit 1
        ;;
esac
