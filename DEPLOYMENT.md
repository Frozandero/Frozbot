# FrozBot VPS Deployment Guide

## Prerequisites
- Ubuntu/Debian VPS with systemd
- Python 3.10+ installed
- Your Discord bot token and configuration

## Setup Steps

### 1. Upload Files to VPS
```bash
# Upload your bot files to your VPS
scp -r ./frozbot user@your-vps-ip:/home/user/
```

### 2. SSH into Your VPS
```bash
ssh user@your-vps-ip
cd frozbot
```

### 3. Configure Environment Variables
```bash
# Copy the example config
cp config.env.example .env

# Edit with your actual values
nano .env
```

Your `.env` file should contain:
```env
DISCORD_BOT_TOKEN=your_actual_bot_token
DISCORD_GUILD_ID=your_guild_id_optional
OWNER_ID=your_discord_user_id
```

### 4. Bootstrap the Service
```bash
# Create the frozbot system user, install to /opt/frozbot, create the venv,
# install dependencies, register the service, and start it.
sudo bash deploy.sh bootstrap
```

The bootstrap command creates a dedicated `frozbot` system user and copies the app to `/opt/frozbot`. This is recommended when the repo was cloned under `/root`, because non-root service users cannot normally read files inside `/root`.

Optional bootstrap overrides:
```bash
sudo FROZBOT_BOOTSTRAP_USER=mybot bash deploy.sh bootstrap
sudo FROZBOT_BOOTSTRAP_DIR=/srv/frozbot bash deploy.sh bootstrap
```

### 5. Manual Service Install
If you already created a virtual environment and want the service to run from the current checkout:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

bash deploy.sh install
bash deploy.sh start
```

The install command generates `/etc/systemd/system/frozbot.service` using the current checkout path and current Unix user. It auto-detects Python from `.venv`, `venv`, or `env` under the repo, then falls back to `python3`/`python` on `PATH`.
The generated unit loads `$BOT_DIR/.env` with `EnvironmentFile=-...`, sets `PYTHONUNBUFFERED=1`, waits for `network-online.target`, and writes structured logs to journald.

Optional overrides:
```bash
FROZBOT_SERVICE_USER=frozbot bash deploy.sh install
FROZBOT_VENV_DIR=/opt/frozbot/.venv bash deploy.sh install
FROZBOT_PYTHON=/opt/frozbot/.venv/bin/python bash deploy.sh install
```

### 6. Manage the Bot
```bash
# Start the bot service if using manual install
bash deploy.sh start

# Check status
bash deploy.sh status

# View logs
bash deploy.sh logs
```

## Managing Your Bot

### Start/Stop/Restart
```bash
bash deploy.sh start    # Start the bot
bash deploy.sh stop     # Stop the bot
bash deploy.sh restart  # Restart the bot
```

### View Status and Logs
```bash
bash deploy.sh status   # Check if bot is running
bash deploy.sh logs     # View real-time logs
```

Logs are structured JSON by default. Set `LOG_LEVEL` in `.env` if you need more or less verbosity.

### Refresh Commands (No Restart Needed!)
After making changes to your bot code:

1. **Upload the updated files** to your VPS
2. **Use the `/refresh` command** in Discord (only you can use this)
3. **Or restart the service**: `bash deploy.sh restart`

## Troubleshooting

### Bot Won't Start
```bash
# Check service status
bash deploy.sh status

# View detailed logs
bash deploy.sh logs

# Check if paths are correct in service file
sudo nano /etc/systemd/system/frozbot.service
```

### Commands Not Updating
- Use `/refresh` in Discord (you only)
- Or restart: `bash deploy.sh restart`
- Check that `OWNER_ID` is set correctly in `.env`

### Permission Issues
```bash
# Check file ownership
ls -la
```

## Security Notes
- Keep your `.env` file secure and never commit it to version control
- The `/refresh` command only works for the user ID specified in `OWNER_ID`
- The bot runs as a system service with automatic restart on failure
