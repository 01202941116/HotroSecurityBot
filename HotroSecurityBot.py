# -*- coding: utf-8 -*-
import os
import re
import logging
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler

# ========= TOKEN =========
# Ưu tiên lấy từ biến môi trường BOT_TOKEN trên Render
TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    # có thể thay tạm ở đây để test local, nhưng khi lên Render hãy set BOT_TOKEN
    TOKEN = "PASTE_YOUR_TOKEN_HERE"

# ========= LIST =========
# Link cho phép (không xóa nếu có chứa 1 trong các domain này)
WHITELIST = ["youtube.com", "youtu.be", "duyenmy.vn"]

# Mẫu cần chặn (xóa nếu KHÔNG thuộc whitelist nhưng khớp 1 trong các pattern này)
BLACKLIST_PATTERNS = [
    r"t\.me",         # link tới kênh/nhóm telegram
    r"@\w+",          # mention @username
    r"\bsex\b",
    r"18\+",
    r"\bxxx\b"
]

# ========= LOGGING =========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger("HotroSecurityBot")

# ========= HELPERS =========
def extract_text(update: Update) -> str:
    msg = update.effective_message
    if not msg:
        return ""
    # Ưu tiên text, nếu không có sẽ lấy caption (ảnh/video) để vẫn lọc được
    return (msg.text or msg.caption or "").lower()

def is_whitelisted(text: str) -> bool:
    return any(domain in text for domain in WHITELIST)

def is_blacklisted(text: str) -> bool:
    return any(re.search(p, text) for p in BLACKLIST_PATTERNS)

# ========= HANDLERS =========
def cmd_start(update: Update, context: CallbackContext):
    update.message.reply_text("🤖 Bot đã bật. Tin nhắn chứa @username, t.me, sex/18+… sẽ bị xóa. "
                              "Link whitelist: " + ", ".join(WHITELIST))

def filter_message(update: Update, context: CallbackContext):
    msg = update.effective_message
    if not msg:
        return

    text = extract_text(update)
    if not text:
        return

    # Cho phép nếu chứa domain trong whitelist
    if is_whitelisted(text):
        return

    # Xóa nếu khớp blacklist
    if is_blacklisted(text):
        try:
            context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
            log.info(f"🗑 Đã xóa: {text[:80]}")
        except Exception as e:
            log.warning(f"Lỗi khi xóa tin nhắn: {e}")

# ========= MAIN =========
def main():
    if not TOKEN or TOKEN == "PASTE_YOUR_TOKEN_HERE":
        raise RuntimeError("Thiếu BOT_TOKEN. Hãy set biến môi trường BOT_TOKEN trên Render.")

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", cmd_start))
    # Lọc cả message text và caption (ảnh/video kèm mô tả)
    dp.add_handler(MessageHandler(Filters.text | Filters.caption, filter_message))

    log.info("🤖 Bot đang chạy...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
