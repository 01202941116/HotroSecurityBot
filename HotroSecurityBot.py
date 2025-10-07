# HotroSecurityBot.py
# Compatible: python-telegram-bot==13.15  (Python 3.11.x)
# Chức năng:
# - Xoá tin nhắn có link ngoài whitelist
# - Chặn @mention, t.me, từ khoá bẩn (sex, 18+, …)
# - Admin có thể xem /status, thêm/xoá domain whitelist tạm thời bằng lệnh
#   (danh sách sẽ mất khi bot restart — đơn giản và nhẹ)

import os
import re
import logging
from typing import Set, List

from telegram import Update
from telegram.ext import (
    Updater,
    CallbackContext,
    MessageHandler,
    Filters,
    CommandHandler,
)

# -------------------- Cấu hình cơ bản --------------------
# Lấy token từ biến môi trường BOT_TOKEN (khuyến nghị).
# Nếu muốn hard-code thì điền thẳng vào fallback bên dưới.
BOT_TOKEN = os.getenv("BOT_TOKEN") or "PASTE_YOUR_BOT_TOKEN_HERE"

# Domain được phép xuất hiện trong tin nhắn (ví dụ link youtube, website của bạn)
WHITELIST: Set[str] = set([
    "youtube.com",
    "youtu.be",
    "duyenmy.vn",
])

# Các mẫu cần chặn (regex, không phân biệt hoa thường)
BLACKLIST_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bt\.me\b", re.I),          # link đến kênh/nhóm Telegram
    re.compile(r"(?<!\w)@\w+", re.I),        # @mentions
    re.compile(r"\bsex\b", re.I),
    re.compile(r"18\+", re.I),
]

# Regex bắt URL đơn giản (http/https + host + optional path)
URL_RE = re.compile(
    r"(?i)\bhttps?://([A-Z0-9.-]+)(?:/[^\s]*)?\b"
)

# -------------------- Logging ----------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("HotroSecurityBot")

# -------------------- Helper -----------------------------
def user_is_admin(update: Update, context: CallbackContext) -> bool:
    """Trả về True nếu người gửi là admin/owner trong group."""
    try:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return False
        member = chat.get_member(user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def urls_in_text(text: str) -> List[str]:
    return [m.group(1).lower() for m in URL_RE.finditer(text or "")]


def url_allowed(host: str) -> bool:
    """Kiểm tra host có thuộc whitelist không (so khớp phần đuôi)."""
    if not host:
        return False
    for allow in WHITELIST:
        allow = allow.lower()
        if host == allow or host.endswith("." + allow):
            return True
    return False


def should_delete(text: str) -> bool:
    """Quyết định có xoá tin nhắn hay không."""
    if not text:
        return False

    # 1) Nếu có link => chỉ cho phép khi mọi link đều thuộc whitelist
    hosts = urls_in_text(text)
    if hosts:
        for h in hosts:
            if not url_allowed(h):
                return True  # có link ngoài whitelist

    # 2) Kiểm blacklist patterns (t.me, @mention, sex, 18+,...)
    for pat in BLACKLIST_PATTERNS:
        if pat.search(text):
            return True

    return False


def try_delete(update: Update, context: CallbackContext) -> None:
    """Thử xoá tin nhắn, nuốt lỗi để bot không crash."""
    try:
        chat_id = update.effective_chat.id
        msg_id = update.effective_message.message_id
        context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception as e:
        log.warning("Không thể xoá tin nhắn: %s", e)


# -------------------- Handlers ---------------------------
def start_cmd(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "🤖 Bot chống spam đã sẵn sàng.\n"
        "• Tự động xoá link ngoài whitelist\n"
        "• Chặn @mention, t.me, và các từ khoá bẩn\n"
        "Lệnh hữu ích: /status, /whitelist_add, /whitelist_remove"
    )


def status_cmd(update: Update, context: CallbackContext) -> None:
    wl = "\n - ".join(sorted(WHITELIST)) or "(trống)"
    update.message.reply_text(
        "✅ Trạng thái bộ lọc:\n"
        f"• Whitelist:\n - {wl}\n"
        "• Blacklist: t.me, @mention, sex, 18+"
    )


def whitelist_add_cmd(update: Update, context: CallbackContext) -> None:
    if not user_is_admin(update, context):
        return
    if not context.args:
        update.message.reply_text("Dùng: /whitelist_add domain.com")
        return
    domain = context.args[0].lower().strip()
    WHITELIST.add(domain)
    update.message.reply_text(f"✅ Đã thêm '{domain}' vào whitelist (tạm thời).")


def whitelist_remove_cmd(update: Update, context: CallbackContext) -> None:
    if not user_is_admin(update, context):
        return
    if not context.args:
        update.message.reply_text("Dùng: /whitelist_remove domain.com")
        return
    domain = context.args[0].lower().strip()
    if domain in WHITELIST:
        WHITELIST.remove(domain)
        update.message.reply_text(f"✅ Đã xoá '{domain}' khỏi whitelist.")
    else:
        update.message.reply_text(f"ℹ️ '{domain}' không có trong whitelist.")


def cleaner(update: Update, context: CallbackContext) -> None:
    """Xử lý mọi tin nhắn văn bản."""
    msg = update.effective_message
    text = (msg.text or msg.caption or "").strip()

    # Cho admin gửi thoải mái
    if user_is_admin(update, context):
        return

    if should_delete(text):
        log.info("Xoá: %s", text)
        try_delete(update, context)


def error_handler(update: object, context: CallbackContext) -> None:
    log.exception("Lỗi không bắt được: %s", context.error)


# -------------------- Main -------------------------------
def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("❌ Thiếu BOT_TOKEN. Đặt env BOT_TOKEN hoặc điền trực tiếp trong mã.")

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Lệnh
    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CommandHandler("status", status_cmd))
    dp.add_handler(CommandHandler("whitelist_add", whitelist_add_cmd))
    dp.add_handler(CommandHandler("whitelist_remove", whitelist_remove_cmd))

    # Lọc tin nhắn (text & caption)
    dp.add_handler(MessageHandler(Filters.text | Filters.caption, cleaner))

    dp.add_error_handler(error_handler)

    log.info("🤖 Bot đang chạy...")
    updater.start_polling(clean=True)
    updater.idle()


if __name__ == "__main__":
    main()
