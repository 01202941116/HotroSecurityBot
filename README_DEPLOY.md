
# HotroSecurityBot — Render Ready

## Env
- BOT_TOKEN=<token bot từ BotFather>
- OWNER_ID=<telegram user id>
- CONTACT_USERNAME=<username liên hệ>

## Build Command
pip uninstall -y telegram || true && pip install --no-cache-dir -r requirements.txt

## Start Command
python main.py

## Notes
- `runtime.txt` pins Python 3.12.5 (PTB 20.7 ổn định trên 3.12).
- Nếu dùng Background Worker: cũng dùng Start `python main.py`.
