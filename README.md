
# HotroSecurityBot — Free + Pro (PTB 20)

Features
- Free + Pro (trial 7 days `/trial7` via /pro, key `/redeem <key>`)
- Admin-only key generation `/genkey <days>`
- Anti-link, keyword filters, anti-flood (mute 5m)
- Auto downgrade when Pro expired
- Flask keep-alive + polling (works on Render)

## Deploy on Render
1. Create a **Web Service**
2. Build command: `pip install -r requirements.txt`
3. Start command: `python main.py`
4. Env Vars:
   - `BOT_TOKEN` = your bot token
   - `OWNER_ID`  = your telegram numeric id
   - `CONTACT_USERNAME` = username for Contact button
   - (optional) `TRIAL_DAYS`, `PRO_DEFAULT_DAYS`
5. Give the bot admin rights in group.

## Commands
- `/filter_add <word>`
- `/filter_list`
- `/filter_del <id>`
- `/antilink_on` | `/antilink_off`
- `/setflood <n>`
- `/pro` `/redeem <key>` `/genkey <days>`

