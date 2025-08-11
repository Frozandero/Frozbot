# FrozBot VPS Deployment Guide

## Prerequisites
- Ubuntu/Debian VPS with systemd
- Python 3.8+ installed
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

### 3. Set Up Python Environment
```bash
# Install Python venv if not already installed
sudo apt update
sudo apt install python3-venv

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure Environment Variables
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

### 5. Install and Start the Service
```bash
# Make deploy script executable
chmod +x deploy.sh

# Install the systemd service
./deploy.sh install

# Edit the service file with correct paths
sudo nano /etc/systemd/system/frozbot.service
```

**Important**: Update these paths in the service file:
- `User=YOUR_USERNAME` → Your actual VPS username
- `WorkingDirectory=/path/to/your/frozbot` → Actual path to your bot
- `Environment=PATH=/path/to/your/frozbot/.venv/bin` → Actual path to your venv

### 6. Start the Bot
```bash
# Start the bot service
./deploy.sh start

# Check status
./deploy.sh status

# View logs
./deploy.sh logs
```

## Managing Your Bot

### Start/Stop/Restart
```bash
./deploy.sh start    # Start the bot
./deploy.sh stop     # Stop the bot
./deploy.sh restart  # Restart the bot
```

### View Status and Logs
```bash
./deploy.sh status   # Check if bot is running
./deploy.sh logs     # View real-time logs
```

### Refresh Commands (No Restart Needed!)
After making changes to your bot code:

1. **Upload the updated files** to your VPS
2. **Use the `/refresh` command** in Discord (only you can use this)
3. **Or restart the service**: `./deploy.sh restart`

## Troubleshooting

### Bot Won't Start
```bash
# Check service status
./deploy.sh status

# View detailed logs
./deploy.sh logs

# Check if paths are correct in service file
sudo nano /etc/systemd/system/frozbot.service
```

### Commands Not Updating
- Use `/refresh` in Discord (you only)
- Or restart: `./deploy.sh restart`
- Check that `OWNER_ID` is set correctly in `.env`

### Permission Issues
```bash
# Make sure deploy script is executable
chmod +x deploy.sh

# Check file ownership
ls -la
```

## Security Notes
- Keep your `.env` file secure and never commit it to version control
- The `/refresh` command only works for the user ID specified in `OWNER_ID`
- The bot runs as a system service with automatic restart on failure
