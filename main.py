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
    await context.bot.send_message(update.effective_chat.id, "Xin chào! Gõ /help để xem lệnh.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "<b>HotroSecurityBot – Full</b>\n\n"
        "<b>FREE</b>\n"
        "/filter_add &lt;từ&gt; – thêm từ khoá chặn\n"
        "/filter_list – xem danh sách từ khoá\n"
        "/filter_del &lt;id&gt; – xoá filter theo ID\n"
        "/antilink_on | /antilink_off\n"
        "/antimention_on | /antimention_off\n"
        "/antiforward_on | /antiforward_off\n"
        "/setflood &lt;n&gt; – giới hạn spam (mặc định 3)\n\n"
        "<b>PRO</b>\n"
        "/pro – bảng dùng thử / nhập key\n"
        "/trial – kích hoạt dùng thử 7 ngày\n"
        "/redeem &lt;key&gt; – kích hoạt\n"
        "/genkey &lt;days&gt; – (OWNER) sinh key\n"
        "/wl_add &lt;domain&gt; | /wl_del &lt;domain&gt; | /wl_list – whitelist link\n"
        "/captcha_on | /captcha_off – bật/tắt captcha join (placeholder)\n"
    )
    await context.bot.send_message(update.effective_chat.id, txt, parse_mode="HTML")

async def filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: <code>/filter_add từ_khoá</code>", parse_mode="HTML")
    pattern = " ".join(context.args).strip()
    if not pattern:
        return await update.message.reply_text("Từ khoá rỗng.")
    db = SessionLocal()
    f = Filter(chat_id=update.effective_chat.id, pattern=pattern)
    db.add(f); db.commit()
    await update.message.reply_text(f"✅ Đã thêm filter #{f.id}: <code>{pattern}</code>", parse_mode="HTML")

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

    # Đừng ăn lệnh
    if msg.text and msg.text.startswith("/"):
        return

    chat_id = update.effective_chat.id
    text = (msg.text or msg.caption or "")

    db = SessionLocal()
    s = get_settings(chat_id)

    # keyword filters
    for it in db.query(Filter).filter_by(chat_id=chat_id).all():
        if it.pattern.lower() in text.lower():
            try: await msg.delete()
            except Exception: pass
            return

    # anti forward
    if s.antiforward and getattr(msg, "forward_origin", None):
        try: await msg.delete()
        except Exception: pass
        return

    # anti link + whitelist
    if s.antilink and LINK_RE.search(text):
        wl = [w.domain for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
        allowed = any(d and d.lower() in text.lower() for d in wl)
        if not allowed:
            try: await msg.delete()
            except Exception: pass
            return

    # anti mention
    if s.antimention and "@" in text:
        try: await msg.delete()
        except Exception: pass
        return

    # anti flood
    key = (chat_id, msg.from_user.id)
    now = datetime.now().timestamp()
    bucket = [t for t in FLOOD.get(key, []) if now - t < 10]
    bucket.append(now); FLOOD[key] =
