## Discord IQ Bot (Python)

A simple Discord bot that replies with a deterministic, fake IQ value based on a user's persistent account information. The bot hashes user info and seeds a normal RNG (mean 100, std 15) to generate a stable result for each user.

### Features
- Deterministic per-user IQ calculation using SHA-256 of stable identifiers
- Normal distribution with mean 100 and standard deviation 15
- Implemented as a slash command: `/iq`

### Prerequisites
- Python 3.10+
- A Discord application and bot token with the following OAuth2 scopes when inviting:
  - `bot`
  - `applications.commands`

### Setup
1. Clone or open this project.
2. Create and activate a virtual environment (recommended):
   - Windows (PowerShell):
     ```powershell
     py -3 -m venv .venv
     .venv\Scripts\Activate.ps1
     ```
   - macOS/Linux:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file in the `discord/` directory. You can start from `env.example`:
   ```bash
   copy env.example .env  # Windows PowerShell
   # or
   cp env.example .env    # macOS/Linux
   ```
   Then edit `.env` and set:
   ```env
   DISCORD_BOT_TOKEN=your-bot-token-here
   # Optional: provide a test guild ID to sync commands instantly in one server
   # If omitted, commands are synced globally (can take up to 1 hour to appear)
   # DISCORD_GUILD_ID=123456789012345678
   ```

### Running
From the `discord/` directory, run:
```bash
python bot.py
```

- If `DISCORD_GUILD_ID` is set, the `/iq` command appears almost immediately in that server.
- If not set, the command syncs globally and may take up to ~1 hour to appear.

### Usage
In any channel where the bot is present, type:
```
/iq
```
The bot will reply with your deterministic fake IQ.

### Notes
- This bot does not require the Message Content intent because it uses slash commands.
- The IQ is not meant to be real or serious; it is purely for entertainment.