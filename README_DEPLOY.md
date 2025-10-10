# HotroSecurityBot (PTB v21)

## Biến môi trường (Render → Environment)
- BOT_TOKEN = <token Telegram BotFather>
- OWNER_ID  = <Telegram user id của bạn>
- CONTACT_USERNAME = <username support, không có @>
- LICENSE_DB_URL (tùy chọn) = sqlite:///licenses.db  (mặc định)
- PORT = 10000  (Render sẽ tự set, không cần nếu đã có)

## Build/Start command
Build: `pip install -r requirements.txt`
Start: `python main.py`

## Ghi chú
- Dịch vụ là Web Service (không phải Background) để giữ sống bằng Flask.
- Free instance có thể sleep; keepalive giúp Render ping đường dẫn gốc.
