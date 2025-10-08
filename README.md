# HotroSecurityBot - Starter Telegram Moderation Bot

**This repository contains a starter implementation for a Telegram group moderation bot**
with basic features: whitelist/blacklist, toggles for link/forward/contact filters, key generation for Pro access,
admin commands, and persistent SQLite storage. It's a starting point — you should test and secure it before running in production.

## Features included in this starter
- /start - welcome and menu
- /status - show current toggles
- /whitelist_add <domain_or_string> - add whitelist entry (admin)
- /whitelist_remove <domain_or_string> - remove whitelist entry (admin)
- /blacklist_add <word_or_domain> - add blacklist entry (admin)
- /blacklist_remove <word_or_domain> - remove blacklist entry (admin)
- /genkey <months> - admin generates a Pro key valid N months
- /keys_list - admin lists generated keys and status
- Message handler: basic detection of URLs and @mentions; checks whitelist/blacklist
- SQLite storage for chat settings, whitelist, blacklist, and keys

## How to configure
1. Copy `.env.example` to `.env` and fill in your BOT_TOKEN and ADMIN_IDS (comma-separated).
2. Install requirements: `pip install -r requirements.txt`
3. Run with polling locally: `python main.py`
   Or deploy to a host (Render/Heroku) and configure a webhook if desired.

## Important notes
- The starter code runs actions like `delete_message` and `ban_chat_member`. Use with caution and test in a private group.
- For production, secure your bot token, enable logging, rate-limiting, and consider using a hosted DB (Postgres) if needed.
- The included NSFW or advanced ML features are placeholders; integrating models requires additional resources.

## License
MIT
