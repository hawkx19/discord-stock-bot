# Virtual Exchange Discord Bot

A Discord slash-command bot for a fictional stock market using virtual coins only.

## Features
- New members start with 100,000 virtual coins.
- The configured owner has an unlimited virtual wallet.
- `/pay` transfers coins; owner transfers do not reduce the owner's unlimited wallet.
- Stock prices never change automatically; only the configured owner can change them.
- `/market`, `/buy`, `/sell`, `/portfolio`, `/balance`, `/leaderboard`.
- Owner-only coin grants, balance changes, price controls, stock creation, and stock halt/resume.
- SQLite persistence.

## Setup
1. Create an application at https://discord.com/developers/applications
2. Under **Bot**, add a bot user and copy its token. Keep the token secret.
3. Under **OAuth2 > URL Generator**, select scopes `bot` and `applications.commands`.
4. Select bot permissions `Send Messages`, `Embed Links`, and `Use Application Commands` if shown. Open the generated URL and invite the bot to your server.
5. Get your Discord user ID: enable Developer Mode in Discord settings, then long-press/right-click your profile and choose **Copy User ID**.
6. Deploy this project on a Python host that supports persistent disk storage. Set environment variables:
   - `DISCORD_TOKEN` = bot token
   - `OWNER_ID` = your numeric Discord user ID
7. Start command: `python bot.py`

## Important hosting note
The SQLite database (`exchange.db`) must live on persistent storage. If a host restarts the worker without persistent disk, balances and holdings may be lost. Free hosting tiers may sleep or change availability; check the host's current plan before relying on 24/7 uptime.

## Commands
- `/balance`
- `/pay member amount`
- `/market`
- `/buy symbol shares`
- `/sell symbol shares`
- `/portfolio`
- `/leaderboard`
- `/help_market`
- `/admin_give member amount`
- `/admin_set_balance member amount`
- `/admin_set_price symbol price`
- `/admin_change_price symbol direction amount percent` (percent=true means percentage; false means coin amount)
- `/admin_add_stock symbol company_name price`
- `/admin_halt_stock symbol`
- `/admin_resume_stock symbol`

## Security
- Never commit your bot token to GitHub or paste it into chat.
- Keep `OWNER_ID` set to your own Discord user ID.
- The bot only uses fictional stocks and virtual coins; it does not connect to real brokerage or payment accounts.
