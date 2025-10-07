# -*- coding: utf-8 -*-
import os
import re
import logging
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler

# ====== TOKEN BOT ======
TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    TOKEN = "8360017614:AAfAdMj06cY9PyGYpHcL9vL03CM8rLbo2I"  # thay bằng token của bạn nếu cần

# ====== DANH SÁCH ======
WHITELIST = ["youtube.com", "duyenmy.vn", "youtu.be"]
BLACKLIST_PATTERNS = [
    r"t\.me",
    r"@\w+",
    r"sex",
    r"18\+",
    r"xxx"
]

# ====== LOGGING ======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger("HotroSecurityBot")

# ====== HÀM XỬ LÝ ======
def extract_text(update: Update) -> str:
    msg = update.effective_message
    if not msg:
        return ""
    return (msg.text or msg.caption or "").lower()

def match_blacklist(text: str) -> bool:
    return any(re.search(p, text) for p in BLACKLIST_PATTERNS)

def start(update: Update, context: CallbackContext):
    update.message.reply_text("🤖 Bot đang hoạt động và sẽ tự xóa tin nhắn vi phạm!")

def filter_message(update: Update, context: CallbackContext):
    msg = update.effective_message
    if not msg or not msg.text:
        return

    text = extract_text(update)

    # Cho phép link trong whitelist
    if any(domain in text for domain in WHITELIST):
        return

    # Xóa nếu khớp blacklist
    if match_blacklist(text):
        try:
            context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
            log.info(f"🗑 Đã xóa tin nhắn vi phạm: {text[:40]}")
        except Exception as e:
            log.warning(f"Lỗi khi xóa tin nhắn: {e}")

# ====== MAIN ======
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text | Filters.caption, filter_message))

    log.info("🤖 Bot đang chạy...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
