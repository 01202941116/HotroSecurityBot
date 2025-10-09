# HotroSecurityBot – PTB 20

**Features**
- Free + Pro (trial 7 days `/trial7`, key `/applykey <key>`)
- Admin-only replies via DM; fallback in group if DM blocked
- Anti-link/@mention, anti-forward, anti-flood (Pro), blacklist/whitelist
- Auto notice when Pro expires
- Flask keep-alive + polling (works on Render)

## Deploy

1. Env vars:
```
BOT_TOKEN=123456:ABC-YourToken
ADMIN_IDS=111111111,222222222
```
2. Install:
```
pip install -r requirements.txt
```
3. Run:
```
python app.py
```
