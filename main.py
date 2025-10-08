# HotroSecurityBot - starter main (Render compatible)
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ================== LOAD ENVIRONMENT ==================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB = "hotrosecurity.db"

# ================== DATABASE INIT ==================
def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS chat_settings (
        chat_id INTEGER PRIMARY KEY,
        nolinks INTEGER DEFAULT 1,
        noforwards INTEGER DEFAULT 1,
        nobots INTEGER DEFAULT 1,
        antiflood INTEGER DEFAULT 1
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS whitelist (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, text TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, text TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS pro_keys (
        key TEXT PRIMARY KEY, months INTEGER, created_at TEXT,
        used_by INTEGER NULL, expires_at TEXT NULL
    )""")
    conn.commit()
    conn.close()

# ================== CORE FUNCTIONS ==================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_setting(chat_id: int):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT nolinks, noforwards, nobots, antiflood FROM chat_settings WHERE chat_id=?", (chat_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO chat_settings(chat_id) VALUES(?)", (chat_id,))
        conn.commit()
        row = (1, 1, 1, 1)
    conn.close()
    return {"nolinks": bool(row[0]), "noforwards": bool(row[1]), "nobots": bool(row[2]), "antiflood": bool(row[3])}

def add_whitelist(chat_id, text):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("INSERT INTO whitelist(chat_id, text) VALUES(?,?)", (chat_id, text))
    conn.commit(); conn.close()

def remove_whitelist(chat_id, text):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("DELETE FROM whitelist WHERE chat_id=? AND text=?", (chat_id, text))
    conn.commit(); conn.close()

def list_whitelist(chat_id):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT text FROM whitelist WHERE chat_id=?", (chat_id,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows

def add_blacklist(chat_id, text):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("INSERT INTO blacklist(chat_id, text) VALUES(?,?)", (chat_id, text))
    conn.commit(); conn.close()

def remove_blacklist(chat_id, text):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("DELETE FROM blacklist WHERE chat_id=? AND text=?", (chat_id, text))
    conn.commit(); conn.close()

def list_blacklist(chat_id):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT text FROM blacklist WHERE chat_id=?", (chat_id,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows

import secrets
def gen_key(months=1):
    key = secrets.token_urlsafe(12)
    created = datetime.utcnow()
    expires = created + timedelta(days=30 * int(months))
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("INSERT INTO pro_keys(key, months, created_at, expires_at) VALUES(?,?,?,?)",
                (key, months, created.isoformat(), expires.isoformat()))
    conn.commit(); conn.close()
    return key, expires

def list_keys():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT key, months, created_at, expires_at, used_by FROM pro_keys")
    rows = cur.fetchall()
    conn.close()
    return rows

# ================== FILTER PATTERNS ==================
URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
MENTION_RE = re.compile(r"@([A-Za-z0-9_]{5,64})")

# ================== COMMANDS ==================
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🤖 HotroSecurityBot đang hoạt động!\n"
        "Dùng /status để xem cấu hình hoặc /help để biết thêm lệnh."
    )

def status(update: Update, context: CallbackContext):
    chat = update.effective_chat
    s = get_setting(chat.id)
    wl = list_whitelist(chat.id)
    bl = list_blacklist(chat.id)
    text = (f"📋 Cấu hình nhóm {chat.title or chat.id}:\n"
            f"nolinks={s['nolinks']}, noforwards={s['noforwards']}, "
            f"nobots={s['nobots']}, antiflood={s['antiflood']}\n"
            f"Whitelist: {', '.join(wl) if wl else '(none)'}\n"
            f"Blacklist: {', '.join(bl) if bl else '(none)'}")
    update.message.reply_text(text)

def whitelist_add(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args:
        update.message.reply_text("Usage: /whitelist_add domain_or_text"); return
    add_whitelist(update.effective_chat.id, ' '.join(context.args).strip())
    update.message.reply_text("✅ Đã thêm vào whitelist.")

def whitelist_remove(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args:
        update.message.reply_text("Usage: /whitelist_remove domain_or_text"); return
    remove_whitelist(update.effective_chat.id, ' '.join(context.args).strip())
    update.message.reply_text("✅ Đã xóa khỏi whitelist.")

def blacklist_add(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args:
        update.message.reply_text("Usage: /blacklist_add domain_or_text"); return
    add_blacklist(update.effective_chat.id, ' '.join(context.args).strip())
    update.message.reply_text("✅ Đã thêm vào blacklist.")

def blacklist_remove(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args:
        update.message.reply_text("Usage: /blacklist_remove domain_or_text"); return
    remove_blacklist(update.effective_chat.id, ' '.join(context.args).strip())
    update.message.reply_text("✅ Đã xóa khỏi blacklist.")

def genkey_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    months = 1
    if context.args:
        try:
            months = int(context.args[0])
        except Exception:
            update.message.reply_text("Usage: /genkey <months>"); return
    key, expires = gen_key(months)
    update.message.reply_text(
        f"🔑 Key mới: `{key}`\nHiệu lực {months} tháng, hết hạn {expires.isoformat()} (UTC)",
        parse_mode=ParseMode.MARKDOWN
    )

def keys_list_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    rows = list_keys()
    if not rows:
        update.message.reply_text("Chưa có key nào."); return
    text = "🗝 Danh sách key:\n" + "\n".join(
        f"{r[0]} | {r[1]} tháng | tạo: {r[2]} | hết hạn: {r[3]} | dùng bởi: {r[4]}" for r in rows
    )
    update.message.reply_text(text)

# ================== MESSAGE HANDLER ==================
def message_handler(update: Update, context: CallbackContext):
    msg = update.message
    if not msg:
        return
    chat_id = update.effective_chat.id
    s = get_setting(chat_id)
    text = msg.text or msg.caption or ""

    wl = list_whitelist(chat_id)
    bl = list_blacklist(chat_id)

    # Blacklist
    if any(b.lower() in text.lower() for b in bl):
        try: msg.delete()
        except Exception as e: logger.warning("delete failed: %s", e)
        return

    urls = URL_RE.findall(text)
    mentions = MENTION_RE.findall(text)

    # Link filter
    if s["nolinks"] and urls:
        allowed = any(any(w.lower() in u.lower() for w in wl) for u in urls)
        if not allowed:
            try: msg.delete()
            except Exception as e: logger.warning("delete failed: %s", e)
            return

    # Mention filter
    if s["nolinks"] and mentions:
        for m in mentions:
            if any(w.lower() in m.lower() for w in wl):
                continue
            try: msg.delete()
            except Exception as e: logger.warning("delete failed: %s", e)
            return

def error_handler(update, context):
    logger.exception("Exception: %s", context.error)

# ================== START TELEGRAM BOT ==================
def start_bot():
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set"); return
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("whitelist_add", whitelist_add, pass_args=True))
    dp.add_handler(CommandHandler("whitelist_remove", whitelist_remove, pass_args=True))
    dp.add_handler(CommandHandler("blacklist_add", blacklist_add, pass_args=True))
    dp.add_handler(CommandHandler("blacklist_remove", blacklist_remove, pass_args=True))
    dp.add_handler(CommandHandler("genkey", genkey_cmd, pass_args=True))
    dp.add_handler(CommandHandler("keys_list", keys_list_cmd))
    dp.add_handler(MessageHandler(Filters.text | Filters.entity("url") | Filters.caption, message_handler))
    dp.add_error_handler(error_handler)
    logger.info("🚀 Starting polling...")
    updater.start_polling()
    updater.idle()

# ================== FLASK PORT KEEP-ALIVE (Render Free) ==================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ HotroSecurityBot đang chạy trên Render Free!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# ================== RUN BOTH THREADS ==================
if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.start()
    start_bot()
