# HotroSecurityBot - full features (Render-compatible, PTB 13.15)
import logging
import os
import re
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask
from telegram import Update, ParseMode, ChatPermissions
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, CallbackContext
)

# ================== ENV ==================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB = "hotrosecurity.db"

# ================== DB & SCHEMA ==================
def _conn():
    return sqlite3.connect(DB)

def init_db():
    conn = _conn(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS chat_settings (
        chat_id INTEGER PRIMARY KEY,
        nolinks INTEGER DEFAULT 1,
        noforwards INTEGER DEFAULT 1,
        nobots INTEGER DEFAULT 1,
        antiflood INTEGER DEFAULT 1,
        noevents INTEGER DEFAULT 0,
        pro_until TEXT NULL
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
    # Ensure columns (for upgrades)
    def ensure_col(col, type_sql):
        cur.execute("PRAGMA table_info(chat_settings)")
        cols = [r[1] for r in cur.fetchall()]
        if col not in cols:
            cur.execute(f"ALTER TABLE chat_settings ADD COLUMN {col} {type_sql}")
            conn.commit()
    ensure_col("noevents", "INTEGER DEFAULT 0")
    ensure_col("pro_until", "TEXT NULL")
    conn.close()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_setting(chat_id: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT nolinks, noforwards, nobots, antiflood, noevents, pro_until "
                "FROM chat_settings WHERE chat_id=?", (chat_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO chat_settings(chat_id) VALUES(?)", (chat_id,))
        conn.commit()
        row = (1, 1, 1, 1, 0, None)
    conn.close()
    return {
        "nolinks": bool(row[0]), "noforwards": bool(row[1]),
        "nobots": bool(row[2]), "antiflood": bool(row[3]),
        "noevents": bool(row[4]),
        "pro_until": (datetime.fromisoformat(row[5]) if row[5] else None)
    }

def set_setting(chat_id: int, key: str, value: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute(f"UPDATE chat_settings SET {key}=? WHERE chat_id=?", (int(value), chat_id))
    conn.commit(); conn.close()

def set_pro_until(chat_id: int, until_dt: datetime):
    conn = _conn(); cur = conn.cursor()
    cur.execute("UPDATE chat_settings SET pro_until=? WHERE chat_id=?", (until_dt.isoformat(), chat_id))
    conn.commit(); conn.close()

def add_whitelist(chat_id, text):
    conn = _conn(); cur = conn.cursor()
    cur.execute("INSERT INTO whitelist(chat_id, text) VALUES(?,?)", (chat_id, text)); conn.commit(); conn.close()

def remove_whitelist(chat_id, text):
    conn = _conn(); cur = conn.cursor()
    cur.execute("DELETE FROM whitelist WHERE chat_id=? AND text=?", (chat_id, text)); conn.commit(); conn.close()

def list_whitelist(chat_id):
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT text FROM whitelist WHERE chat_id=?", (chat_id,))
    rows = [r[0] for r in cur.fetchall()]; conn.close(); return rows

def add_blacklist(chat_id, text):
    conn = _conn(); cur = conn.cursor()
    cur.execute("INSERT INTO blacklist(chat_id, text) VALUES(?,?)", (chat_id, text)); conn.commit(); conn.close()

def remove_blacklist(chat_id, text):
    conn = _conn(); cur = conn.cursor()
    cur.execute("DELETE FROM blacklist WHERE chat_id=? AND text=?", (chat_id, text)); conn.commit(); conn.close()

def list_blacklist(chat_id):
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT text FROM blacklist WHERE chat_id=?", (chat_id,))
    rows = [r[0] for r in cur.fetchall()]; conn.close(); return rows

# Keys
import secrets
def gen_key(months=1):
    key = secrets.token_urlsafe(12)
    created = datetime.utcnow()
    expires = created + timedelta(days=30 * int(months))
    conn = _conn(); cur = conn.cursor()
    cur.execute("INSERT INTO pro_keys(key, months, created_at, expires_at) VALUES(?,?,?,?)",
                (key, months, created.isoformat(), expires.isoformat()))
    conn.commit(); conn.close()
    return key, expires

def list_keys():
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT key, months, created_at, expires_at, used_by FROM pro_keys")
    rows = cur.fetchall(); conn.close(); return rows

def consume_key(key: str, user_id: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT key, months, created_at, expires_at, used_by FROM pro_keys WHERE key=?", (key,))
    row = cur.fetchone()
    if not row:
        conn.close(); return False, "invalid key", None
    if row[4] is not None:
        conn.close(); return False, "used", None
    exp = datetime.fromisoformat(row[3])
    if exp < datetime.utcnow():
        conn.close(); return False, "expired", None
    cur.execute("UPDATE pro_keys SET used_by=? WHERE key=?", (user_id, key))
    conn.commit(); conn.close()
    return True, None, int(row[1])

# ================== FILTERS & STATE ==================
URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
MENTION_RE = re.compile(r"@([A-Za-z0-9_]{5,64})")

# Simple anti-flood: 3 messages / 20s per user
FLOOD_WINDOW = 20
FLOOD_LIMIT = 3
user_buckets = {}  # {(chat_id, user_id): deque[timestamps]}

def _is_flood(chat_id, user_id):
    key = (chat_id, user_id)
    dq = user_buckets.get(key)
    now = time.time()
    if dq is None:
        dq = deque(maxlen=FLOOD_LIMIT); user_buckets[key] = dq
    # drop old
    while dq and now - dq[0] > FLOOD_WINDOW:
        dq.popleft()
    dq.append(now)
    return len(dq) > FLOOD_LIMIT

# ================== COMMANDS ==================
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🤖 HotroSecurityBot đang hoạt động!\n"
        "Dùng /status để xem cấu hình hoặc /help để biết thêm lệnh."
    )

def help_cmd(update: Update, context: CallbackContext):
    is_ad = is_admin(update.effective_user.id)
    text = [
        "🛟 *HƯỚNG DẪN SỬ DỤNG*",
        "",
        "• `/start` – Kiểm tra bot",
        "• `/status` – Xem cấu hình & thời hạn Pro",
        "",
        "*Bật/Tắt (admin)*",
        "• `/nolinks on|off` – Bật/tắt chặn link & @mention",
        "• `/noforwards on|off` – Chặn tin nhắn forward",
        "• `/nobots on|off` – Chặn thành viên mời bot vào",
        "• `/antiflood on|off` – Chống spam (3 tin/20s)",
        "• `/noevents on|off` – Ẩn thông báo join/left",
        "",
        "*Whitelist/Blacklist (admin)*",
        "• `/whitelist_add <từ|domain>` / `/whitelist_remove <...>`",
        "• `/whitelist_list` – Liệt kê whitelist",
        "• `/blacklist_add <từ|domain>` / `/blacklist_remove <...>`",
        "• `/blacklist_list` – Liệt kê blacklist",
        "",
        "*Pro*",
        "• `/applykey <key>` – Kích hoạt Pro cho *nhóm hiện tại*",
        "*Pro (admin tạo key)*",
        "• `/genkey <tháng>` – Tạo key",
        "• `/keys_list` – Liệt kê key",
    ]
    if not is_ad:
        text.append("\n⚠️ Một số lệnh chỉ dành cho admin (ADMIN_IDS).")
    update.message.reply_text("\n".join(text), parse_mode=ParseMode.MARKDOWN)

def status(update: Update, context: CallbackContext):
    chat = update.effective_chat
    s = get_setting(chat.id)
    wl = list_whitelist(chat.id)
    bl = list_blacklist(chat.id)
    pro_txt = f"Pro: đến {s['pro_until'].isoformat()} (UTC)" if s["pro_until"] else "Pro: (chưa kích hoạt)"
    text = (f"📋 Cấu hình nhóm {chat.title or chat.id}:\n"
            f"- nolinks={s['nolinks']} | noforwards={s['noforwards']} | "
            f"nobots={s['nobots']} | antiflood={s['antiflood']} | noevents={s['noevents']}\n"
            f"- {pro_txt}\n"
            f"- Whitelist: {', '.join(wl) if wl else '(none)'}\n"
            f"- Blacklist: {', '.join(bl) if bl else '(none)'}")
    update.message.reply_text(text)

# toggles
def _toggle(update: Update, context: CallbackContext, field: str):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args or context.args[0].lower() not in ("on","off"):
        update.message.reply_text(f"Usage: /{field} on|off"); return
    val = 1 if context.args[0].lower()=="on" else 0
    set_setting(update.effective_chat.id, field, val)
    update.message.reply_text(f"✅ {field} = {'on' if val else 'off'}")

def nolinks(update, context): _toggle(update, context, "nolinks")
def noforwards(update, context): _toggle(update, context, "noforwards")
def nobots(update, context): _toggle(update, context, "nobots")
def antiflood(update, context): _toggle(update, context, "antiflood")
def noevents(update, context): _toggle(update, context, "noevents")

# white/black list
def whitelist_add(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args: update.message.reply_text("Usage: /whitelist_add <từ|domain>"); return
    add_whitelist(update.effective_chat.id, ' '.join(context.args).strip())
    update.message.reply_text("✅ Đã thêm vào whitelist.")

def whitelist_remove(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args: update.message.reply_text("Usage: /whitelist_remove <từ|domain>"); return
    remove_whitelist(update.effective_chat.id, ' '.join(context.args).strip())
    update.message.reply_text("✅ Đã xóa khỏi whitelist.")

def whitelist_list_cmd(update: Update, context: CallbackContext):
    wl = list_whitelist(update.effective_chat.id)
    update.message.reply_text("Whitelist:\n" + ("\n".join(wl) if wl else "(none)"))

def blacklist_add(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args: update.message.reply_text("Usage: /blacklist_add <từ|domain>"); return
    add_blacklist(update.effective_chat.id, ' '.join(context.args).strip())
    update.message.reply_text("✅ Đã thêm vào blacklist.")

def blacklist_remove(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args: update.message.reply_text("Usage: /blacklist_remove <từ|domain>"); return
    remove_blacklist(update.effective_chat.id, ' '.join(context.args).strip())
    update.message.reply_text("✅ Đã xóa khỏi blacklist.")

def blacklist_list_cmd(update: Update, context: CallbackContext):
    bl = list_blacklist(update.effective_chat.id)
    update.message.reply_text("Blacklist:\n" + ("\n".join(bl) if bl else "(none)"))

# Keys
def genkey_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    months = 1
    if context.args:
        try: months = int(context.args[0])
        except Exception: update.message.reply_text("Usage: /genkey <tháng>"); return
    key, expires = gen_key(months)
    update.message.reply_text(
        f"🔑 Key mới: `{key}`\nHiệu lực {months} tháng, hết hạn {expires.isoformat()} (UTC)",
        parse_mode=ParseMode.MARKDOWN
    )

def keys_list_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    rows = list_keys()
    if not rows: update.message.reply_text("Chưa có key nào."); return
    text = "🗝 Danh sách key:\n" + "\n".join(
        f"{r[0]} | {r[1]} tháng | tạo:{r[2]} | hết hạn:{r[3]} | used_by:{r[4]}" for r in rows
    )
    update.message.reply_text(text)

def applykey_cmd(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.effective_user
    if not context.args:
        update.message.reply_text("Usage: /applykey <key>\n(Lưu ý: kích hoạt cho *nhóm hiện tại*)",
                                  parse_mode=ParseMode.MARKDOWN)
        return
    key = context.args[0].strip()
    ok, reason, months = consume_key(key, user.id)
    if not ok:
        m = {"invalid key":"❌ Key không hợp lệ",
             "used":"❌ Key đã sử dụng",
             "expired":"❌ Key đã hết hạn"}.get(reason, "❌ Không thể dùng key")
        update.message.reply_text(m); return
    # set pro for this chat
    cur = get_setting(chat.id)
    now = datetime.utcnow()
    base = cur["pro_until"] if cur["pro_until"] and cur["pro_until"] > now else now
    new_until = base + timedelta(days=30*months)
    set_pro_until(chat.id, new_until)
    update.message.reply_text(f"✅ Đã kích hoạt Pro cho nhóm đến: {new_until.isoformat()} (UTC)")

# ================== EVENTS & MODERATION ==================
def delete_service_messages(update: Update, context: CallbackContext):
    s = get_setting(update.effective_chat.id)
    if s["noevents"]:
        try: update.effective_message.delete()
        except Exception: pass

def new_members(update: Update, context: CallbackContext):
    s = get_setting(update.effective_chat.id)
    if s["noevents"]:
        try: update.effective_message.delete()
        except Exception: pass
    if s["nobots"]:
        for m in update.effective_message.new_chat_members:
            if m.is_bot:
                try:
                    context.bot.kick_chat_member(update.effective_chat.id, m.id)
                except Exception as e:
                    logger.warning("kick bot fail: %s", e)

def message_handler(update: Update, context: CallbackContext):
    msg = update.message
    if not msg: return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    s = get_setting(chat_id)

    # Anti-flood
    if s["antiflood"] and not is_admin(user_id):
        if _is_flood(chat_id, user_id):
            try: msg.delete()
            except Exception: pass
            return

    # Block forwards
    if s["noforwards"] and (msg.forward_date or msg.forward_from or msg.forward_from_chat):
        try: msg.delete()
        except Exception: pass
        return

    text = msg.text or msg.caption or ""
    wl = list_whitelist(chat_id)
    bl = list_blacklist(chat_id)

    # Pro: ưu tiên blacklist mạnh hơn & siết mention
    if any(b.lower() in text.lower() for b in bl):
        try: msg.delete()
        except Exception: pass
        return

    urls = URL_RE.findall(text)
    mentions = MENTION_RE.findall(text)

    # Link filter
    if s["nolinks"] and urls:
        allowed = any(any(w.lower() in u.lower() for w in wl) for u in urls)
        if not allowed:
            try: msg.delete()
            except Exception: pass
            return

    # Mention filter (siết chặt hơn nếu Pro còn hạn)
    pro_active = bool(s["pro_until"] and s["pro_until"] > datetime.utcnow())
    if s["nolinks"] and mentions:
        for m in mentions:
            ok = any(w.lower() in m.lower() for w in wl)
            if pro_active:
                # Ở Pro: nếu m không thuộc whitelist -> xoá ngay
                if not ok:
                    try: msg.delete()
                    except Exception: pass
                    return
            else:
                if not ok:
                    try: msg.delete()
                    except Exception: pass
                    return

def error_handler(update, context):
    logger.exception("Exception: %s", context.error)

# ================== START BOT ==================
def start_bot():
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set"); return
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("nolinks", nolinks, pass_args=True))
    dp.add_handler(CommandHandler("noforwards", noforwards, pass_args=True))
    dp.add_handler(CommandHandler("nobots", nobots, pass_args=True))
    dp.add_handler(CommandHandler("antiflood", antiflood, pass_args=True))
    dp.add_handler(CommandHandler("noevents", noevents, pass_args=True))

    dp.add_handler(CommandHandler("whitelist_add", whitelist_add, pass_args=True))
    dp.add_handler(CommandHandler("whitelist_remove", whitelist_remove, pass_args=True))
    dp.add_handler(CommandHandler("whitelist_list", whitelist_list_cmd))

    dp.add_handler(CommandHandler("blacklist_add", blacklist_add, pass_args=True))
    dp.add_handler(CommandHandler("blacklist_remove", blacklist_remove, pass_args=True))
    dp.add_handler(CommandHandler("blacklist_list", blacklist_list_cmd))

    dp.add_handler(CommandHandler("genkey", genkey_cmd, pass_args=True))
    dp.add_handler(CommandHandler("keys_list", keys_list_cmd))
    dp.add_handler(CommandHandler("applykey", applykey_cmd, pass_args=True))

    # events
    dp.add_handler(MessageHandler(Filters.status_update, delete_service_messages))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_members))

    # messages
    dp.add_handler(MessageHandler(Filters.text | Filters.entity("url") | Filters.caption, message_handler))

    dp.add_error_handler(error_handler)
    logger.info("🚀 Starting polling...")
    updater.start_polling()
    updater.idle()

# ================== FLASK KEEP-ALIVE (Render Free) ==================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ HotroSecurityBot is running (Render Free)."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# ================== RUN ==================
if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.start()
    start_bot()
