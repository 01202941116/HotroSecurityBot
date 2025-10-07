from telegram.ext import Updater, MessageHandler, Filters
import re

# 🔑 Token bot của bạn:
TOKEN = "8360017614:AAfAdMj06cY9PyGYpHcL9vL03CM8rLbo2I"

# ✅ Danh sách domain cho phép (whitelist)
WHITELIST = ["youtube.com", "duyenmy.vn"]

# 🚫 Danh sách cần chặn (blacklist)
BLACKLIST_PATTERNS = [
    r"t\.me",
    r"@", 
    r"\.com",
    r"sex",
    r"18\+"
]

def delete_spam(update, context):
    if not update.message or not update.message.text:
        return
    msg = update.message.text.lower()
    for wl in WHITELIST:
        if wl in msg:
            return
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, msg):
            try:
                context.bot.delete_message(update.message.chat_id, update.message.message_id)
                print(f"🗑 Đã xóa tin nhắn vi phạm: {msg}")
            except Exception as e:
                print(f"Lỗi khi xóa tin nhắn: {e}")
            return

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, delete_spam))
    print("🤖 Bot đang chạy...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
