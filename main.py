from keepalive import start_keepalive

def main():
    ...
    start_keepalive()
    ...
import os
import re
import threading
from datetime import datetime, timedelta

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

from core.models import init_db, SessionLocal, Setting, Filter, Whitelist
from pro.handlers import register_handlers
from pro.scheduler import attach_scheduler
from keepalive import run as keepalive_run

# ====== ENV ======
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME", "").strip()

# ====== STATE ======
FLOOD = {}
LINK_RE = re.compile(r"(https?://|t\.me/|@\w+)", re.IGNORECASE)

# ====== HELPERS ======
def get_settings(chat_id: int) -> Setting:
    db = SessionLocal()
    s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
    if not s:
        s = Setting(
            chat_id=chat_id,
            antilink=True,
            antimention=True,
            antiforward=True,
            flood_limit=3,
            flood_mode="mute",
        )
        db.add(s)
        db.commit()
    return s

# ====== COMMANDS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id,
        "Xin chào! Gõ /help để xem lệnh."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🔥 <b>HotroSecurityBot – Hệ thống bảo vệ nhóm Telegram</b>\n\n"
        "🔹 <b>FREE:</b>\n"
        "/filter_add <từ> – thêm từ khoá chặn\n"
        "/filter_list – xem danh sách từ khoá\n"
        "/filter_del <id> – xoá filter theo ID\n"
        "/antilink_on | /antilink_off – chống link\n"
        "/antimention_on | /antimention_off – chống tag\n"
        "/antiforward_on | /antiforward_off – chống forward\n"
        "/setflood <số tin> – giới hạn spam (mặc định 3)\n\n"
        "💎 <b>PRO:</b>\n"
        "/pro – xem bản quyền / nhập key\n"
        "/redeem <key> – kích hoạt key\n"
        "/genkey <days> – (OWNER) tạo key dùng thử\n"
        "/wl_add <domain> | /wl_del <domain> | /wl_list – whitelist link\n"
        "/captcha_on | /captcha_off – bật/tắt captcha join\n\n"
        f"Hỗ trợ: @{CONTACT_USERNAME or 'admin'}"
    )
    await update.message.reply_text(txt, parse_mode="HTML")

async def filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Cú pháp: <code>/filter_add từ_khoá</code>", parse_mode="HTML"
        )
    pattern = " ".join(context.args).strip()
    if not pattern:
        return await update.message.reply_text("Từ khoá rỗng.")
    db = SessionLocal()
    f = Filter(chat_id=update.effective_chat.id, pattern=pattern)
    db.add(f); db.commit()
    await update.message.reply_text(
        f"✅ Đã thêm filter #{f.id}: <code>{pattern}</code>", parse_mode="HTML"
    )

async def filter_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    items = db.query(Filter).filter_by(chat_id=update.effective_chat.id).all()
    if not items:
        return await update.message.reply_text("Danh sách filter trống.")
    out = ["<b>Filters:</b>"] + [f"{i.id}. <code>{i.pattern}</code>" for i in items]
    await update.message.reply_text("\n".join(out), parse_mode="HTML")

async def filter_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /filter_del <id>")
    try:
        fid = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("ID không hợp lệ.")
    db = SessionLocal()
    it = db.query(Filter).filter_by(id=fid, chat_id=update.effective_chat.id).one_or_none()
    if not it:
        return await update.message.reply_text("Không tìm thấy ID.")
    db.delete(it); db.commit()
    await update.message.reply_text(f"🗑️ Đã xoá filter #{fid}.")

async def toggle(update: Update, field: str, val: bool, label: str):
    db = SessionLocal()
    s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
    if not s:
        s = Setting(chat_id=update.effective_chat.id)
        db.add(s)
    setattr(s, field, val)
    db.commit()
    await update.message.reply_text(("✅ Bật " if val else "❎ Tắt ") + label + ".")

async def antilink_on(update, context):     await toggle(update, "antilink", True,  "Anti-link")
async def antilink_off(update, context):    await toggle(update, "antilink", False, "Anti-link")
async def antimention_on(update, context):  await toggle(update, "antimention", True,  "Anti-mention")
async def antimention_off(update, context): await toggle(update, "antimention", False, "Anti-mention")
async def antiforward_on(update, context):  await toggle(update, "antiforward", True,  "Anti-forward")
async def antiforward_off(update, context): await toggle(update, "antiforward", False, "Anti-forward")

async def setflood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /setflood <số tin>")
    try:
        n = max(2, int(context.args[0]))
    except ValueError:
        return await update.message.reply_text("Giá trị không hợp lệ.")
    db = SessionLocal()
    s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
    if not s:
        s = Setting(chat_id=update.effective_chat.id)
        db.add(s)
    s.flood_limit = n
    db.commit()
    await update.message.reply_text(f"✅ Flood limit = {n}")

# ====== GUARD ======
async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    # Không xử lý commands để tránh nuốt /start, /help,...
    if msg.text and msg.text.startswith("/"):
        return

    chat_id = update.effective_chat.id
    text = (msg.text or msg.caption or "")

    db = SessionLocal()
    s = get_settings(chat_id)

    # keyword filters
    for it in db.query(Filter).filter_by(chat_id=chat_id).all():
        if it.pattern.lower() in text.lower():
            try:
                await msg.delete()
            except Exception:
                pass
            return

    # anti forward
    if s.antiforward and getattr(msg, "forward_origin", None):
        try:
            await msg.delete()
        except Exception:
            pass
        return

    # anti link + whitelist
    if s.antilink and LINK_RE.search(text):
        wl = [w.domain for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
        allowed = any(d and d.lower() in text.lower() for d in wl)
        if not allowed:
            try:
                await msg.delete()
            except Exception:
                pass
            return

    # anti mention
    if s.antimention and "@" in text:
        try:
            await msg.delete()
        except Exception:
            pass
        return

    # anti flood
    key = (chat_id, msg.from_user.id)
    now = datetime.now().timestamp()
    bucket = [t for t in FLOOD.get(key, []) if now - t < 10]
    bucket.append(now)
    FLOOD[key] = bucket
    if len(bucket) > s.flood_limit and s.flood_mode == "mute":
        try:
            until = datetime.now() + timedelta(minutes=5)
            await context.bot.restrict_chat_member(
                chat_id,
                msg.from_user.id,
                ChatPermissions(can_send_messages=False),
                until_date=until,
            )
        except Exception:
            pass

# ====== error log (để log ra console thay vì crash) ======
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        print("ERROR:", repr(context.error))
    except Exception:
        pass

# ====== startup hook ======
async def on_startup(app: Application):
    try:
        me = await app.bot.get_me()
        app.bot_data["contact"] = me.username or CONTACT_USERNAME
    except Exception:
        app.bot_data["contact"] = CONTACT_USERNAME or "admin"

# ====== MAIN ======
def main():
    if not BOT_TOKEN:
        raise SystemExit("Missing BOT_TOKEN")

    print("PTB boot — token len:", len(BOT_TOKEN), "prefix:", BOT_TOKEN[:10], "…")
    try:
        from telegram import __version__ as _ptb_ver
        print("PTB version =", _ptb_ver)
    except Exception:
        pass

    init_db()

    # Keepalive (Flask) để Render free không ngủ quá lâu
    try:
        threading.Thread(target=keepalive_run, daemon=True).start()
    except Exception:
        pass

    app = Application.builder().token(BOT_TOKEN).build()

    # Gán đúng kiểu (PTB 21.x): post_init là callback attribute, không phải callable
    app.post_init = on_startup
    app.add_error_handler(on_error)

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("filter_add", filter_add))
    app.add_handler(CommandHandler("filter_list", filter_list))
    app.add_handler(CommandHandler("filter_del", filter_del))
    app.add_handler(CommandHandler("antilink_on", antilink_on))
    app.add_handler(CommandHandler("antilink_off", antilink_off))
    app.add_handler(CommandHandler("antimention_on", antimention_on))
    app.add_handler(CommandHandler("antimention_off", antimention_off))
    app.add_handler(CommandHandler("antiforward_on", antiforward_on))
    app.add_handler(CommandHandler("antiforward_off", antiforward_off))
    app.add_handler(CommandHandler("setflood", setflood))

    # Pro features
    register_handlers(app)
    attach_scheduler(app)

    # Guard: KHÔNG bắt command
    app.add_handler(MessageHandler(~filters.StatusUpdate.ALL & ~filters.COMMAND, guard))

    print("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
