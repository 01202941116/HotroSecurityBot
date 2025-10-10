# main.py
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
LINK_RE = re.compile(r"(https?://|t\.me/|@\w+)")

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
    await context.bot.send_message(chat_id, "Xin chào! Gõ /help để xem lệnh.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "<b>HotroSecurityBot – Full</b>\n\n"
        "<b>FREE</b>\n"
        "/filter_add <từ> – thêm từ khoá chặn\n"
        "/filter_list – xem danh sách từ khoá\n"
        "/filter_del <id> – xoá filter theo ID\n"
        "/antilink_on | /antilink_off\n"
        "/antimention_on | /antimention_off\n"
        "/antiforward_on | /antiforward_off\n"
        "/setflood <n> – giới hạn spam (mặc định 3)\n\n"
        "<b>PRO</b>\n"
        "/pro – bảng dùng thử / nhập key\n"
        "/redeem <key> – kích hoạt\n"
        "/genkey <days> – (OWNER) sinh key\n"
        "/wl_add <domain> | /wl_del <domain> | /wl_list – whitelist link\n"
        "/captcha_on | /captcha_off – bật/tắt captcha join\n"
    )
    await context.bot.send_message(update.effective_chat.id, txt, parse_mode="HTML")

async def filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Cú pháp: <code>/filter_add @spam</code>", parse_mode="HTML"
        )
    pattern = " ".join(context.args)
    db = SessionLocal()
    f = Filter(chat_id=update.effective_chat.id, pattern=pattern)
    db.add(f)
    db.commit()
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
    fid = int(context.args[0])
    db = SessionLocal()
    it = db.query(Filter).filter_by(id=fid, chat_id=update.effective_chat.id).one_or_none()
    if not it:
        return await update.message.reply_text("Không tìm thấy ID.")
    db.delete(it)
    db.commit()
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

async def antilink_on(update, context):    await toggle(update, "antilink",    True,  "Anti-link")
async def antilink_off(update, context):   await toggle(update, "antilink",    False, "Anti-link")
async def antimention_on(update, context): await toggle(update, "antimention", True,  "Anti-mention")
async def antimention_off(update, context):await toggle(update, "antimention", False, "Anti-mention")
async def antiforward_on(update, context): await toggle(update, "antiforward", True,  "Anti-forward")
async def antiforward_off(update, context):await toggle(update, "antiforward", False, "Anti-forward")

async def setflood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /setflood <số tin>")
    n = max(2, int(context.args[0]))
    db = SessionLocal()
    s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
    if not s:
        s = Setting(chat_id=update.effective_chat.id)
        db.add(s)
    s.flood_limit = n
    db.commit()
    await update.message.reply_text(f"✅ Flood limit = {n}")

# ====== GUARD (anti spam/link/mention/forward) ======
async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    # Tuyệt đối không xử lý command
    if (msg.text and msg.text.startswith("/")) or (msg.entities and any(e.type == "bot_command" for e in msg.entities)):
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

    # anti forward (PTB 21.x)
    if s.antiforward and getattr(msg, "forward_origin", None):
        try:
            await msg.delete()
        except Exception:
            pass
        return

    # anti link với whitelist
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
    bucket = FLOOD.get(key, [])
    bucket = [t for t in bucket if now - t < 10]
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

# ====== STARTUP HOOK ======
async def on_startup(app: Application):
    try:
        me = await app.bot.get_me()
        app.bot_data["contact"] = me.username or CONTACT_USERNAME
        print("Bot ready as @", app.bot_data["contact"])
    except Exception as e:
        print("post_init error:", e)
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

    # keepalive (Flask) cho Render free
    try:
        threading.Thread(target=keepalive_run, daemon=True).start()
    except Exception:
        pass

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init(on_startup)

    # --- HANDLER ORDER (group): 0 = cao nhất
    # 1) Commands (ưu tiên)
    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("help", help_cmd), group=0)
    app.add_handler(CommandHandler("filter_add", filter_add), group=0)
    app.add_handler(CommandHandler("filter_list", filter_list), group=0)
    app.add_handler(CommandHandler("filter_del", filter_del), group=0)
    app.add_handler(CommandHandler("antilink_on", antilink_on), group=0)
    app.add_handler(CommandHandler("antilink_off", antilink_off), group=0)
    app.add_handler(CommandHandler("antimention_on", antimention_on), group=0)
    app.add_handler(CommandHandler("antimention_off", antimention_off), group=0)
    app.add_handler(CommandHandler("antiforward_on", antiforward_on), group=0)
    app.add_handler(CommandHandler("antiforward_off", antiforward_off), group=0)
    app.add_handler(CommandHandler("setflood", setflood), group=0)

    # 2) Pro handlers (đặt sau commands)
    register_handlers(app, group=1)

    # 3) Guard: KHÔNG bắt command & chạy sau cùng
    app.add_handler(
        MessageHandler((~filters.StatusUpdate.ALL) & (~filters.COMMAND), guard),
        group=2
    )

    # Schedulers
    attach_scheduler(app)

    print("Bot started.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )

if __name__ == "__main__":
    main()
