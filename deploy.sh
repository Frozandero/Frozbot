#!/bin/bash

# FrozBot Deployment Script
# Usage: ./deploy.sh bootstrap [--copy-env]
#        ./deploy.sh [install|start|stop|restart|status|logs|refresh]

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
Environment=PYTHONUNBUFFERED=1
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
        COPY_ENV=false
        case "${2:-}" in
            "")
                ;;
            --copy-env)
                COPY_ENV=true
                ;;
            *)
                echo "Error: unknown bootstrap option: $2"
                echo "Usage: $0 bootstrap [--copy-env]"
                exit 1
                ;;
        esac
        if [ "$#" -gt 2 ]; then
            echo "Error: bootstrap accepts only the optional --copy-env flag."
            echo "Usage: $0 bootstrap [--copy-env]"
            exit 1
        fi

        if [ "$(id -u)" -ne 0 ]; then
            echo "Error: bootstrap must be run as root."
            echo "Use sudo ./deploy.sh bootstrap [--copy-env]"
            exit 1
        fi
        if [ "$COPY_ENV" = true ] && [ ! -f "$SCRIPT_DIR/.env" ]; then
            echo "Error: --copy-env was requested, but $SCRIPT_DIR/.env does not exist."
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
            --exclude ".env" \
            --exclude ".env.*" \
            --exclude ".venv/" \
            --exclude "venv/" \
            --exclude "env/" \
            --exclude "database.db" \
            --exclude "temp_media/" \
            --exclude "__pycache__/" \
            --exclude "*.pyc" \
            --exclude ".pytest_cache/" \
            --exclude ".mypy_cache/" \
            --exclude ".ruff_cache/" \
            --exclude ".coverage" \
            --exclude "htmlcov/" \
            --exclude "*.log" \
            "$SCRIPT_DIR/" "$BOOTSTRAP_DIR/"

        chown -R "$BOOTSTRAP_USER:$BOOTSTRAP_USER" "$BOOTSTRAP_DIR"

        if [ "$COPY_ENV" = true ]; then
            install -m 600 -o "$BOOTSTRAP_USER" -g "$BOOTSTRAP_USER" "$SCRIPT_DIR/.env" "$BOOTSTRAP_DIR/.env"
            echo ".env copied to $BOOTSTRAP_DIR/.env"
            if command -v sha256sum >/dev/null 2>&1; then
                echo "  Source .env sha256:    $(sha256sum "$SCRIPT_DIR/.env" | awk '{print $1}')"
                echo "  Installed .env sha256: $(sha256sum "$BOOTSTRAP_DIR/.env" | awk '{print $1}')"
            fi
        elif [ -f "$BOOTSTRAP_DIR/.env" ]; then
            chown "$BOOTSTRAP_USER:$BOOTSTRAP_USER" "$BOOTSTRAP_DIR/.env"
            chmod 600 "$BOOTSTRAP_DIR/.env"
            echo "Existing $BOOTSTRAP_DIR/.env preserved (use --copy-env to replace it)."
        else
            echo "Warning: $BOOTSTRAP_DIR/.env does not exist."
            echo "Create it manually or rerun bootstrap with --copy-env."
        fi

        sudo -u "$BOOTSTRAP_USER" python3 -m venv "$BOOTSTRAP_DIR/.venv"
        sudo -u "$BOOTSTRAP_USER" "$BOOTSTRAP_DIR/.venv/bin/python" -m pip install -r "$BOOTSTRAP_DIR/requirements.txt"

        FROZBOT_BOT_DIR="$BOOTSTRAP_DIR" \
        FROZBOT_SERVICE_USER="$BOOTSTRAP_USER" \
        FROZBOT_VENV_DIR="$BOOTSTRAP_DIR/.venv" \
        FROZBOT_PYTHON="$BOOTSTRAP_DIR/.venv/bin/python" \
            bash "$BOOTSTRAP_DIR/deploy.sh" install

        systemctl enable "$SERVICE_NAME"
        systemctl restart "$SERVICE_NAME"
        echo "FrozBot bootstrapped and restarted."
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
        echo "Or restart the bot to sync changes: bash deploy.sh restart"
        ;;
    install)
        install_service
        ;;
    *)
        echo "Usage: $0 bootstrap [--copy-env]"
        echo "       $0 {install|start|stop|restart|status|logs|refresh}"
        echo ""
        echo "Commands:"
        echo "  bootstrap - Deploy to /opt/frozbot, preserving .env and runtime data"
        echo "              Use --copy-env to replace the deployed .env from this checkout"
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
