# -*- coding: utf-8 -*-
import os
import re
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ====== TOKEN BOT ======
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
if not TOKEN:
    TOKEN = "8360017614:AAfAdMj06cY9PyGYpHcL9vL03CM8rLbo2I"

# ====== DANH SÁCH ======
WHITELIST = ["youtube.com", "youtu.be", "duyenmy.vn"]
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

# ====== HÀM HỖ TRỢ ======
def is_admin(update: Update, context: CallbackContext) -> bool:
    try:
        member = context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

def extract_text(update: Update) -> str:
    msg = update.effective_message
    if not msg:
        return ""
    return (msg.text or msg.caption or "").lower()

def contains_whitelist(text: str) -> bool:
    return any(domain in text for domain in WHITELIST)

def match_blacklist(text: str) -> bool:
    return any(re.search(p, text) for p in BLACKLIST_PATTERNS)

# ====== HANDLERS ======
def start_cmd(update: Update, context: CallbackContext):
    update.message.reply_text("🤖 Bot đã hoạt động — sẽ tự xoá tin nhắn vi phạm!")

def filter_message(update: Update, context: CallbackContext):
    msg = update.effective_message
    if not msg or is_admin(update, context):
        return
    text = extract_text(update)
    if not text:
        return

    if any(keyword in text for keyword in WHITELIST):
        return

    if match_blacklist(text):
        try:
            context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
            log.info(f"🗑 Đã xoá tin nhắn: {text[:50]}")
        except Exception as e:
            log.warning(f"Không thể xoá tin nhắn: {e}")

# ====== MAIN ======
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(MessageHandler(Filters.text | Filters.caption, filter_message))
    log.info("🤖 Bot đang chạy...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
