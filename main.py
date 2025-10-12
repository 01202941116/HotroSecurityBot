import sys
sys.modules.pop("core.models", None)

import os, re
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from telegram import Update, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton

from telegram import Update, ChatPermissions
from telegram.constants import ParseMode
from telegram.error import Conflict
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ===== LOCAL IMPORTS =====
from core.models import (
    init_db, SessionLocal, Setting, Filter, Whitelist,
    User, count_users, Warning, Blacklist, PromoSetting
)
from core.lang import t, LANG  # ✅ thêm dòng này

from keep_alive_server import keep_alive

# ===== ENV =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME", "").strip()

# ===== STATE / REGEX =====
USER_LANG = {}  # ✅ lưu ngôn ngữ người dùng
FLOOD = {}
LINK_RE = re.compile(
    r"(https?://|www\.|t\.me/|@\w+|[a-zA-Z0-9-]+\.(com|net|org|vn|xyz|info|io|co)(/[^\s]*)?)",
    re.IGNORECASE
)

def remove_links(text: str) -> str:
    return re.sub(LINK_RE, "[link bị xóa]", text or "")

# ====== PRO MODULES (SAFE IMPORT) ======
try:
    from pro.handlers import register_handlers
except Exception:
    register_handlers = lambda app, **kw: None

try:
    from pro.scheduler import attach_scheduler
except Exception:
    attach_scheduler = lambda app: None

# ====== UPTIME UTILS ======
START_AT = datetime.now(timezone.utc)

def _fmt_td(td: timedelta) -> str:
    s = int(td.total_seconds())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return " ".join([f"{d}d" if d else "", f"{h}h" if h else "", f"{m}m" if m else "", f"{s}s"]).strip()

# ====== HELPERS ======
def get_settings(chat_id: int) -> Setting:
    db = SessionLocal()
    s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
    if not s:
        s = Setting(chat_id=chat_id, antilink=True, antimention=True, antiforward=True, flood_limit=3, flood_mode="mute")
        db.add(s)
        db.commit()
    return s

# ====== /LANG COMMAND ======
async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chuyển đổi ngôn ngữ hiển thị"""
    user = update.effective_user
    chat_id = update.effective_chat.id

    if not context.args:
        return await update.message.reply_text(t("vi", "lang_usage"))

    code = context.args[0].lower()
    if code not in LANG:
        return await update.message.reply_text(t("vi", "lang_usage"))

    USER_LANG[user.id] = code
    await context.bot.send_message(
        chat_id,
        t(code, "lang_switched")
    )

# ====== /HELP COMMAND ======
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    lang = USER_LANG.get(uid, "vi")
    txt = t(lang, "help_full", CONTACT_USERNAME=CONTACT_USERNAME)
    await context.bot.send_message(
        update.effective_chat.id,
        txt,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

# ====== /START ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = SessionLocal()
    u = db.get(User, user.id)
    if not u:
        u = User(id=user.id, username=user.username or "")
        db.add(u)
        db.commit()

    total = count_users()
    lang = USER_LANG.get(user.id, "vi")

    # ===== Tạo nút chọn ngôn ngữ =====
    keyboard = [
        [
            InlineKeyboardButton("🇻🇳 Tiếng Việt", callback_data="lang_vi"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # ===== Gửi lời chào =====
    msg = t(lang, "start", name=user.first_name, count=total)
    msg += "\n\n🌐 Chọn ngôn ngữ / Choose language:"
    await context.bot.send_message(
        update.effective_chat.id,
        msg,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

# ====== STATUS / STATS ======
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = count_users()
    await update.message.reply_text(f"📊 Tổng người dùng bot: {total:,}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t0 = datetime.now(timezone.utc)
    m = await update.message.reply_text("⏳ Đang đo ping…")
    dt = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    up = datetime.now(timezone.utc) - START_AT
    await m.edit_text(f"✅ Online | 🕒 Uptime: {_fmt_td(up)} | 🏓 Ping: {dt:.0f} ms")

# ====== PING / UPTIME ======
async def uptime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    up = datetime.now(timezone.utc) - START_AT
    await update.message.reply_text(f"⏱ Uptime: {_fmt_td(up)}")

async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t0 = datetime.now(timezone.utc)
    m = await update.message.reply_text("Pinging…")
    dt = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    await m.edit_text(f"🏓 Pong: {dt:.0f} ms")

# ====== ERROR HANDLER ======
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, Conflict):
        return
    err = repr(context.error)
    print("ERROR:", err)
    try:
        if OWNER_ID:
            await context.bot.send_message(OWNER_ID, f"⚠️ Error:\n<code>{err}</code>", parse_mode=ParseMode.HTML)
    except:
        pass

# ====== STARTUP ======
async def on_startup(app: Application):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except:
        pass
    if OWNER_ID:
        try:
            await app.bot.send_message(OWNER_ID, "🔁 Bot restarted và đang hoạt động!")
        except:
            pass

# ====== MAIN ======
def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ Missing BOT_TOKEN")

    print("🚀 Booting bot...")
    init_db()

    try:
        keep_alive()
    except:
        pass

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = on_startup
    app.add_error_handler(on_error)

    # --- Command handlers ---
    app.add_handler(CommandHandler("lang", lang_cmd))      # ✅ thêm
    app.add_handler(CommandHandler("help", help_cmd))      # ✅ đa ngôn ngữ
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("uptime", uptime_cmd))
    app.add_handler(CallbackQueryHandler(on_lang_button))

    # Có thể giữ nguyên các handler khác (filter_add, warn, ad_on...) của bạn ở đây

    print("✅ Bot started, polling Telegram updates...")
    app.run_polling(drop_pending_updates=True, timeout=60)


if __name__ == "__main__":
    main()
