
import os, re
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN") or "8360017614:AAHo_H0e3HNxq_U1S-o5n0Ps1ifI5Q1XaXo"
OWNER_ID = int(os.getenv("OWNER_ID","5427455644"))
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME","Myyduyenng")

from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from pro.models import init_db, SessionLocal, Filter, Setting
from pro.handlers import register_handlers
from pro.scheduler import attach_scheduler
from keepalive import run as keepalive_run

FLOOD = {}

def get_settings(chat_id):
    db = SessionLocal()
    s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
    if not s:
        s = Setting(chat_id=chat_id, antilink=False, flood_limit=3, flood_mode="mute")
        db.add(s); db.commit()
    return s

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Xin chào! Bot đang hoạt động. /help để xem lệnh.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "<b>HotroSecurityBot</b>\n\n"
        "<b>FREE</b>\n"
        "/filter_add <từ>  – thêm từ khóa chặn\n"
        "/filter_list      – liệt kê từ khóa\n"
        "/filter_del <id>  – xoá filter theo ID\n"
        "/antilink_on | /antilink_off\n"
        "/setflood <n>     – giới hạn số tin liên tục (mặc định 3)\n"
        "\n<b>PRO</b>\n"
        "/pro – mở bảng dùng thử / nhập key\n"
        "/redeem <key> – kích hoạt key\n"
    )
    await update.message.reply_text(txt, parse_mode="HTML")

async def filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: <code>/filter_add @tanxac</code>", parse_mode="HTML")
    pattern = " ".join(context.args)
    db = SessionLocal()
    f = Filter(chat_id=update.effective_chat.id, pattern=pattern)
    db.add(f); db.commit()
    await update.message.reply_text(f"✅ Đã thêm filter #{f.id}: <code>{pattern}</code>", parse_mode="HTML")

async def filter_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    items = db.query(Filter).filter_by(chat_id=update.effective_chat.id).all()
    if not items:
        return await update.message.reply_text("Danh sách filter trống.")
    out = ["<b>Filters:</b>"]
    for it in items:
        out.append(f"{it.id}. <code>{it.pattern}</code>")
    await update.message.reply_text("\n".join(out), parse_mode="HTML")

async def filter_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /filter_del <id>")
    fid = int(context.args[0])
    db = SessionLocal()
    it = db.query(Filter).filter_by(id=fid, chat_id=update.effective_chat.id).one_or_none()
    if not it:
        return await update.message.reply_text("Không tìm thấy ID.")
    db.delete(it); db.commit()
    await update.message.reply_text(f"🗑️ Đã xoá filter #{fid}.")

async def antilink_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_settings(update.effective_chat.id); s.antilink = True; SessionLocal().commit()
    await update.message.reply_text("✅ Anti-link đã bật.")

async def antilink_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_settings(update.effective_chat.id); s.antilink = False; SessionLocal().commit()
    await update.message.reply_text("❎ Anti-link đã tắt.")

async def setflood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /setflood <số tin> (vd: /setflood 3)")
    n = max(2, int(context.args[0]))
    db = SessionLocal()
    s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
    if not s:
        s = Setting(chat_id=update.effective_chat.id, flood_limit=n)
        db.add(s)
    else:
        s.flood_limit = n
    db.commit()
    await update.message.reply_text(f"✅ Flood limit = {n}")

import re
LINK_RE = re.compile(r"(https?://|t\\.me/|@\\w+)")

async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    text = (msg.text or msg.caption or "")
    db = SessionLocal()

    s = get_settings(chat_id)
    filters = db.query(Filter).filter_by(chat_id=chat_id).all()
    for it in filters:
        if it.pattern.lower() in text.lower():
            try:
                await msg.delete()
            except Exception:
                pass
            return
    if s.antilink and LINK_RE.search(text):
        try:
            await msg.delete()
        except Exception:
            pass
        return
    key = (chat_id, msg.from_user.id)
    now = datetime.now().timestamp()
    ts = FLOOD.get(key, [])
    ts = [t for t in ts if now - t < 10]
    ts.append(now)
    FLOOD[key] = ts
    if len(ts) > s.flood_limit:
        if s.flood_mode == "mute":
            until = datetime.now() + timedelta(minutes=5)
            try:
                await context.bot.restrict_chat_member(
                    chat_id, msg.from_user.id,
                    ChatPermissions(can_send_messages=False),
                    until_date=until
                )
            except Exception:
                pass

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"Your ID: <code>{u.id}</code>", parse_mode="HTML")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("id", my_id))
    app.add_handler(CommandHandler("filter_add", filter_add))
    app.add_handler(CommandHandler("filter_list", filter_list))
    app.add_handler(CommandHandler("filter_del", filter_del))
    app.add_handler(CommandHandler("antilink_on", antilink_on))
    app.add_handler(CommandHandler("antilink_off", antilink_off))
    app.add_handler(CommandHandler("setflood", setflood))

    from pro.handlers import register_handlers
    register_handlers(app)

    app.add_handler(MessageHandler(filters.ALL & (~filters.StatusUpdate.ALL), guard))

    from pro.scheduler import attach_scheduler
    attach_scheduler(app)

    import threading
    from keepalive import run as keepalive_run
    threading.Thread(target=keepalive_run, daemon=True).start()

    print("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
