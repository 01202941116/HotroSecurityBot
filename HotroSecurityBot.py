import os
import re
from telegram.ext import Updater, MessageHandler, Filters

# ====== CẤU HÌNH ======
# Lấy token từ biến môi trường (Render -> Environment -> Add "TELEGRAM_TOKEN")
TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()

# Danh sách domain cho phép (whitelist)
WHITELIST = [
    "youtube.com",
    "youtu.be",
    "duyenmy.vn",
]

# Mẫu cần chặn (blacklist). Dùng regex, không phân biệt hoa thường.
BLACKLIST_PATTERNS = [
    r"t\.me",        # link kênh/nhóm Telegram
    r"@\w+",        # mention @username
    r"sex",         # từ nhạy cảm
    r"18\+",        # 18+
    r"\.com",       # chặn .com (trừ domain trong whitelist)
]

# ====== HÀM TIỆN ÍCH ======

def has_whitelisted_domain(text: str) -> bool:
    """Kiểm tra xem trong text có chứa domain whitelist không."""
    if not text:
        return False
    text_l = text.lower()
    for d in WHITELIST:
        if d in text_l:
            return True
    return False

def matches_blacklist(text: str) -> bool:
    """Text có khớp một trong các pattern blacklist không?"""
    if not text:
        return False
    text_l = text.lower()
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, text_l):
            return True
    return False

def get_all_text(update) -> str:
    """Lấy mọi text có thể xuất hiện: text, caption…"""
    msg = update.message
    if not msg:
        return ""
    # ghép text + caption nếu có
    parts = []
    if msg.text:
        parts.append(msg.text)
    if msg.caption:
        parts.append(msg.caption)
    return "\n".join(parts).strip()

# ====== HANDLER CHÍNH ======

def anti_spam_handler(update, context):
    try:
        msg = update.message
        if not msg:
            return

        # Gộp text + caption
        text = get_all_text(update)

        # Nếu là tin nhắn forward, thường là quảng cáo → xử lý như text
        # (nếu bạn muốn xóa tất cả forward luôn, bỏ comment dòng dưới)
        # if msg.forward_from or msg.forward_from_chat:
        #     should_delete = True

        # Cho phép nếu chứa domain whitelist
        if has_whitelisted_domain(text):
            return

        # Nếu khớp blacklist → xóa
        if matches_blacklist(text):
            context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
            print(f"🗑 Đã xóa tin nhắn vi phạm: {text[:120]}")
            return

    except Exception as e:
        print(f"[anti_spam_handler] Lỗi: {e}")

def main():
    if not TOKEN:
        raise RuntimeError(
            "Thiếu TELEGRAM_TOKEN. Vào Render → Environment → Add Variable: "
            "Key=TELEGRAM_TOKEN, Value=<token của BotFather>"
        )

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Chặn mọi tin nhắn chữ/caption (không phải command)
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, anti_spam_handler))
    dp.add_handler(MessageHandler(Filters.caption, anti_spam_handler))
    # Nếu muốn áp cho cả media (ảnh/video/… có hoặc không có caption), giữ dòng dưới:
    dp.add_handler(MessageHandler(Filters.photo | Filters.video | Filters.document | Filters.animation, anti_spam_handler))

    print("🤖 Bot đang chạy…")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
