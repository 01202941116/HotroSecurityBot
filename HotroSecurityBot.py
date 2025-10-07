import os
import re
from telegram.ext import Updater, MessageHandler, Filters

# ====== CẤU HÌNH ======
# Token bot Telegram – bạn có thể lấy từ biến môi trường trên Render
TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
# Nếu chạy thử local thì có thể gán trực tiếp token để test:
if not TOKEN:
    TOKEN = "8360017614:AAfAdMj06cY9PyGYpHcL9vL03CM8rLbo2I"

# Danh sách domain cho phép (whitelist)
WHITELIST = [
    "youtube.com",
    "youtu.be",
    "duyenmy.vn"
]

# Danh sách cần chặn (blacklist)
BLACKLIST_PATTERNS = [
    r"t\.me",        # chặn link Telegram
    r"@\w+",         # chặn @username
    r"sex",
    r"18\+",
    r"\.com"         # chặn các domain .com lạ (ngoài whitelist)
]

# ====== CÁC HÀM HỖ TRỢ ======

def has_whitelisted_domain(text: str) -> bool:
    """Kiểm tra nếu tin nhắn có chứa domain cho phép"""
    if not text:
        return False
    text_l = text.lower()
    return any(d in text_l for d in WHITELIST)

def matches_blacklist(text: str) -> bool:
    """Kiểm tra nếu tin nhắn khớp danh sách cần chặn"""
    if not text:
        return False
    text_l = text.lower()
    return any(re.search(p, text_l) for p in BLACKLIST_PATTERNS)

def get_message_text(update):
    """Lấy text hoặc caption trong tin nhắn"""
    msg = update.message
    if not msg:
        return ""
    parts = []
    if msg.text:
        parts.append(msg.text)
    if msg.caption:
        parts.append(msg.caption)
    return "\n".join(parts).strip()

# ====== XỬ LÝ CHÍNH ======

def delete_spam(update, context):
    try:
        msg = update.message
        if not msg:
            return
        text = get_message_text(update)
        if has_whitelisted_domain(text):
            return
        if matches_blacklist(text):
            context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
            print(f"🗑 Đã xóa tin nhắn vi phạm: {text[:120]}")
    except Exception as e:
        print(f"Lỗi khi xóa tin nhắn: {e}")

def main():
    if not TOKEN:
        raise RuntimeError(
            "⚠️ Thiếu TELEGRAM_TOKEN. Hãy vào Render → Environment → Add Variable: "
            "Key=TELEGRAM_TOKEN, Value=<token của BotFather>"
        )

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Gắn bộ lọc text, caption, media
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, delete_spam))
    dp.add_handler(MessageHandler(Filters.caption, delete_spam))
    dp.add_handler(MessageHandler(Filters.photo | Filters.video | Filters.document | Filters.animation, delete_spam))

    print("🤖 Bot đang chạy…")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
