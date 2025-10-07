# -*- coding: utf-8 -*-
import os
import re
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ====== Cấu hình ======
# Lấy token từ biến môi trường TELEGRAM_TOKEN (khuyên dùng trên Render)
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()

# Cho phép link các domain sau (whitelist)
WHITELIST = {
    "youtube.com",
    "youtu.be",
    "duyenmy.vn",
    "yandex.com",
}

# Từ khoá / mẫu cần chặn (blacklist)
BLACKLIST_PATTERNS = [
    r"t\.me\/?\w*",          # link kênh / group Telegram
    r"@\w{3,}",              # @username mention
    r"\bsex\b",
    r"18\+",                 # 18+
    r"xxx",                  # xxx
]

# ====== Logging ======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("HotroSecurityBot")

# ====== Helpers ======
def is_admin(update: Update, context: CallbackContext) -> bool:
    """Kiểm tra xem người gửi có phải admin không (admin được phép)."""
    try:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return False
        member = context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

def extract_text(update: Update) -> str:
    """Lấy text hoặc caption từ message, đưa về lowercase."""
    msg = update.effective_message
    if not msg:
        return ""
    raw = msg.text or msg.caption or ""
    return raw.lower()

def contains_whitelist(text: str) -> bool:
    """Nếu text có chứa bất kỳ domain được whitelisted -> cho phép."""
    for domain in WHITELIST:
        if domain in text:
            return True
    return False

def looks_like_url(text: str) -> bool:
    """Phát hiện có URL (để kết hợp với whitelist)."""
    # Rất đơn giản & đủ dùng cho lọc cơ bản
    return bool(re.search(r"(https?://|www\.)\S+", text))

def match_blacklist(text: str) -> str:
    """Trả về pattern nào match (nếu có), để log & xoá."""
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return pattern
    return ""

# ====== Handlers ======
def start_cmd(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "🤖 Bot bảo vệ đã hoạt động.\n"
        "• Tự động xoá quảng cáo, mention, link không cho phép.\n"
        "• Whitelist: " + ", ".join(sorted(WHITELIST))
    )

def filter_message(update: Update, context: CallbackContext) -> None:
    msg = update.effective_message
    if not msg:
        return

    # Bỏ qua admin
    if is_admin(update, context):
        return

    text = extract_text(update)
    if not text:
        return

    # 1) Nếu là URL nhưng KHÔNG thuộc whitelist -> xoá
    if looks_like_url(text) and not contains_whitelist(text):
        _delete(update, context, reason="URL không thuộc whitelist")
        return

    # 2) Nếu dính blacklist pattern -> xoá
    hit = match_blacklist(text)
    if hit:
        _delete(update, context, reason=f"Khớp blacklist: {hit}")
        return

def _delete(update: Update, context: CallbackContext, reason: str) -> None:
    msg = update.effective_message
    chat_id = msg.chat_id
    msg_id = msg.message_id
    try:
        context.bot.delete_message(chat_id, msg_id)
        log.info("🗑 Xoá tin nhắn %s (chat=%s, msg_id=%s): %s", reason, chat_id, msg_id, (msg.text or msg.caption or "").strip())
    except Exception as e:
        log.warning("Không xoá được tin nhắn: %s", e)

# ====== Main ======
def main() -> None:
    if not TOKEN:
        log.error("Thiếu TELEGRAM_TOKEN. Hãy set Environment Variable TELEGRAM_TOKEN trên Render.")
        return

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_cmd))
    # Lọc mọi tin nhắn text, caption (ảnh/video kèm caption)
    dp.add_handler(MessageHandler(
        Filters.text | Filters.caption,  # PTB 13.15 không có Filters.caption riêng, dùng như thế này
        filter_message
    ))

    log.info("🤖 Bot đang chạy…")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
