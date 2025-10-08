# HotroSecurityBot - Stable (Render + PTB 13.15)
# - Admin-only private replies (fallback tự xóa trong nhóm nếu không DM được)
# - Free features: nolinks, noforwards, nobots, whitelist/blacklist
# - Pro features: antiflood, noevents  (kích hoạt bằng /applykey <key>)
# - Mạng ổn định hơn: request timeouts + error handler

import logging, os, re, sqlite3, threading, time, secrets
from collections import deque
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask

from telegram import Update, ParseMode
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, CallbackContext
)
from telegram.error import TimedOut, NetworkError, BadRequest, Unauthorized

# ================== ENV ==================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("HotroSecurityBot")

DB = "hotrosecurity.db"

# ================== DB ==================
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
    conn.commit(); conn.close()

# ================== HELPERS ==================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def now_utc():
    return datetime.utcnow()

def get_setting(chat_id: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT nolinks, noforwards, nobots, antiflood, noevents, pro_until
                   FROM chat_settings WHERE chat_id=?""", (chat_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO chat_settings(chat_id) VALUES(?)", (chat_id,))
        conn.commit()
        row = (1, 1, 1, 1, 0, None)
    conn.close()
    return {
        "nolinks": bool(row[0]),
        "noforwards": bool(row[1]),
        "nobots": bool(row[2]),
        "antiflood": bool(row[3]),
        "noevents": bool(row[4]),
        "pro_until": datetime.fromisoformat(row[5]) if row[5] else None
    }

def is_pro(chat_id: int) -> bool:
    s = get_setting(chat_id)
    return bool(s["pro_until"] and s["pro_until"] > now_utc())

def set_setting(chat_id: int, key: str, value: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute(f"UPDATE chat_settings SET {key}=? WHERE chat_id=?", (int(value), chat_id))
    conn.commit(); conn.close()

def set_pro_until(chat_id: int, until_dt: datetime):
    conn = _conn(); cur = conn.cursor()
    cur.execute("UPDATE chat_settings SET pro_until=? WHERE chat_id=?", (until_dt.isoformat(), chat_id))
    conn.commit(); conn.close()

# -------- WL/BL --------
def add_whitelist(chat_id, text):
    conn=_conn();cur=conn.cursor()
    cur.execute("INSERT INTO whitelist(chat_id,text) VALUES(?,?)",(chat_id,text))
    conn.commit();conn.close()

def remove_whitelist(chat_id, text):
    conn=_conn();cur=conn.cursor()
    cur.execute("DELETE FROM whitelist WHERE chat_id=? AND text=?",(chat_id,text))
    conn.commit();conn.close()

def list_whitelist(chat_id):
    conn=_conn();cur=conn.cursor()
    cur.execute("SELECT text FROM whitelist WHERE chat_id=?",(chat_id,))
    r=[x[0] for x in cur.fetchall()];conn.close();return r

def add_blacklist(chat_id,text):
    conn=_conn();cur=conn.cursor()
    cur.execute("INSERT INTO blacklist(chat_id,text) VALUES(?,?)",(chat_id,text))
    conn.commit();conn.close()

def remove_blacklist(chat_id,text):
    conn=_conn();cur=conn.cursor()
    cur.execute("DELETE FROM blacklist WHERE chat_id=? AND text=?",(chat_id,text))
    conn.commit();conn.close()

def list_blacklist(chat_id):
    conn=_conn();cur=conn.cursor()
    cur.execute("SELECT text FROM blacklist WHERE chat_id=?",(chat_id,))
    r=[x[0] for x in cur.fetchall()];conn.close();return r

# -------- Pro keys --------
def gen_key(months=1):
    key = secrets.token_urlsafe(12)
    created = now_utc()
    expires = created + timedelta(days=30*int(months))
    conn=_conn();cur=conn.cursor()
    cur.execute("INSERT INTO pro_keys(key,months,created_at,expires_at) VALUES(?,?,?,?)",
                (key,months,created.isoformat(),expires.isoformat()))
    conn.commit();conn.close()
    return key,expires

def list_keys():
    conn=_conn();cur=conn.cursor()
    cur.execute("SELECT key,months,created_at,expires_at,used_by FROM pro_keys")
    rows=cur.fetchall(); conn.close()
    return rows

def consume_key(key: str, user_id: int):
    conn=_conn();cur=conn.cursor()
    cur.execute("SELECT key,months,created_at,expires_at,used_by FROM pro_keys WHERE key=?",(key,))
    row=cur.fetchone()
    if not row: conn.close(); return False,"invalid",None
    if row[4]: conn.close(); return False,"used",None
    exp=datetime.fromisoformat(row[3])
    if exp<now_utc(): conn.close(); return False,"expired",None
    cur.execute("UPDATE pro_keys SET used_by=? WHERE key=?",(user_id,key))
    conn.commit();conn.close()
    return True,None,int(row[1])

# ================== Messaging helpers ==================
def _delete_later(bot, chat_id, message_id, seconds=5):
    def worker():
        time.sleep(seconds)
        try:
            bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()

def safe_reply_private(update: Update, context: CallbackContext, text: str, **kwargs):
    """
    Gửi DM tới người gọi lệnh (thường là admin).
    Nếu không DM được (Unauthorized | BadRequest) thì gửi trong nhóm rồi tự xóa sau vài giây.
    """
    user_id = update.effective_user.id
    chat = update.effective_chat
    try:
        context.bot.send_message(chat_id=user_id, text=text, **kwargs)
    except (Unauthorized, BadRequest) as e:
        # Fallback thông báo tạm trong nhóm
        if chat and chat.type in ("group", "supergroup"):
            try:
                m = context.bot.send_message(
                    chat_id=chat.id,
                    text="ℹ️ Mình không thể nhắn riêng cho bạn. Hãy mở DM với bot (ấn Start) rồi thử lại.",
                    disable_web_page_preview=True
                )
                _delete_later(context.bot, chat.id, m.message_id, seconds=7)
            except Exception:
                pass
        logger.warning("safe_reply_private fallback group: %s", e)
    except Exception as e:
        logger.warning("safe_reply_private other error: %s", e)

# ================== FILTERS / STATE ==================
URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
MENTION_RE = re.compile(r"@([A-Za-z0-9_]{5,64})")

FLOOD_WINDOW, FLOOD_LIMIT = 20, 3
user_buckets = {}

def _is_flood(chat_id, user_id):
    k=(chat_id,user_id);dq=user_buckets.get(k);now=time.time()
    if dq is None:
        dq=deque(maxlen=FLOOD_LIMIT);user_buckets[k]=dq
    while dq and now-dq[0]>FLOOD_WINDOW:
        dq.popleft()
    dq.append(now)
    return len(dq)>FLOOD_LIMIT

# ================== COMMANDS ==================
def start(update,context):
    safe_reply_private(update,context,"🤖 HotroSecurityBot đang hoạt động!\nDùng /help để xem lệnh.")

def _help_text_free():
    return """🛡 *HƯỚNG DẪN SỬ DỤNG CƠ BẢN*

/status – Xem cấu hình & thời hạn Pro
/nolinks on|off – Chặn link & @mention
/noforwards on|off – Chặn tin nhắn forward
/nobots on|off – Cấm mời bot vào nhóm

📜 Danh sách:
/whitelist_add <text> /whitelist_remove <text>
/blacklist_add <text> /blacklist_remove <text>
/whitelist_list /blacklist_list

🔑 Nâng cấp:
/applykey <key> – Kích hoạt gói Pro
/genkey <tháng> – (Admin) tạo key dùng thử
""".strip()

def _help_text_pro():
    return """💎 *HOTRO SECURITY PRO – ĐÃ KÍCH HOẠT*

Cơ bản:
- /status
- /nolinks on|off
- /noforwards on|off
- /nobots on|off

Pro:
- /antiflood on|off – Chống spam (3 tin/20s)
- /noevents on|off – Ẩn join/left

Danh sách:
- /whitelist_add <text> /whitelist_remove <text>
- /blacklist_add <text> /blacklist_remove <text>
- /whitelist_list /blacklist_list

Key:
- /applykey <key> – Gia hạn/kích hoạt
- /genkey <tháng> – (Admin) tạo key
- /keys_list – (Admin) xem key
""".strip()

def help_cmd(update,context):
    chat = update.effective_chat
    user_id = update.effective_user.id
    if chat.type in ("group","supergroup") and not is_admin(user_id):
        return
    text = _help_text_pro() if is_pro(chat.id) else _help_text_free()
    safe_reply_private(update,context,text,parse_mode=ParseMode.MARKDOWN,disable_web_page_preview=True)

def status(update,context):
    s=get_setting(update.effective_chat.id)
    wl=list_whitelist(update.effective_chat.id); bl=list_blacklist(update.effective_chat.id)
    pro_txt=f"⏳ Pro đến {s['pro_until'].strftime('%d/%m/%Y %H:%M UTC')}" if s["pro_until"] else "❌ Chưa có Pro"
    txt=(f"📋 Cấu hình:\n"
         f"nolinks={s['nolinks']} | noforwards={s['noforwards']} | nobots={s['nobots']} | "
         f"antiflood={s['antiflood']} | noevents={s['noevents']}\n{pro_txt}\n"
         f"Whitelist: {', '.join(wl) if wl else '(trống)'}\n"
         f"Blacklist: {', '.join(bl) if bl else '(trống)'}")
    safe_reply_private(update,context,txt)

# ================== TOGGLES ==================
def _toggle(update,context,field,pro=False):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin.");return
    if pro and not is_pro(update.effective_chat.id):
        safe_reply_private(update,context,f"🔒 {field} chỉ dành cho Pro.");return
    if not context.args or context.args[0].lower() not in ("on","off"):
        safe_reply_private(update,context,f"Usage: /{field} on|off");return
    val=1 if context.args[0].lower()=="on" else 0
    set_setting(update.effective_chat.id,field,val)
    safe_reply_private(update,context,f"✅ {field} = {'on' if val else 'off'}")

def nolinks(u,c): _toggle(u,c,"nolinks")
def noforwards(u,c): _toggle(u,c,"noforwards")
def nobots(u,c): _toggle(u,c,"nobots")
def antiflood(u,c): _toggle(u,c,"antiflood",pro=True)
def noevents(u,c): _toggle(u,c,"noevents",pro=True)

# ================== LIST CMDS ==================
def whitelist_add_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_reply_private(update,context,"Usage: /whitelist_add <text>"); return
    add_whitelist(update.effective_chat.id, " ".join(context.args).strip())
    safe_reply_private(update,context,"✅ Đã thêm vào whitelist.")

def whitelist_remove_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_reply_private(update,context,"Usage: /whitelist_remove <text>"); return
    remove_whitelist(update.effective_chat.id, " ".join(context.args).strip())
    safe_reply_private(update,context,"✅ Đã xoá khỏi whitelist.")

def whitelist_list_cmd(update,context):
    wl = list_whitelist(update.effective_chat.id)
    safe_reply_private(update,context,"📄 Whitelist:\n" + ("\n".join(wl) if wl else "(trống)"))

def blacklist_add_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_reply_private(update,context,"Usage: /blacklist_add <text>"); return
    add_blacklist(update.effective_chat.id, " ".join(context.args).strip())
    safe_reply_private(update,context,"✅ Đã thêm vào blacklist.")

def blacklist_remove_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_reply_private(update,context,"Usage: /blacklist_remove <text>"); return
    remove_blacklist(update.effective_chat.id, " ".join(context.args).strip())
    safe_reply_private(update,context,"✅ Đã xoá khỏi blacklist.")

def blacklist_list_cmd(update,context):
    bl = list_blacklist(update.effective_chat.id)
    safe_reply_private(update,context,"📄 Blacklist:\n" + ("\n".join(bl) if bl else "(trống)"))

# ================== KEY CMDS ==================
def genkey_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    months = 1
    if context.args:
        try: months = int(context.args[0])
        except: 
            safe_reply_private(update,context,"Usage: /genkey <tháng>"); return
    k, exp = gen_key(months)
    safe_reply_private(update,context,
        f"🔑 Key: `{k}`\nHiệu lực {months} tháng (tạo đến {exp.strftime('%d/%m/%Y %H:%M UTC')}).",
        parse_mode=ParseMode.MARKDOWN
    )

def keys_list_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    rows = list_keys()
    if not rows:
        safe_reply_private(update,context,"(Chưa có key)"); return
    out = ["🗝 Danh sách key:"]
    for k, m, c, e, u in rows:
        out.append(f"{k} | {m} tháng | tạo:{c} | hết hạn:{e} | used_by:{u}")
    safe_reply_private(update,context,"\n".join(out))

def applykey_cmd(update,context):
    if not context.args:
        safe_reply_private(update,context,"Usage: /applykey <key>");return
    ok,reason,months=consume_key(context.args[0].strip(),update.effective_user.id)
    if not ok:
        m={"invalid":"❌ Key sai","used":"❌ Key đã dùng","expired":"❌ Key hết hạn"}[reason]
        safe_reply_private(update,context,m);return
    s=get_setting(update.effective_chat.id)
    base=s["pro_until"] if s["pro_until"] and s["pro_until"]>now_utc() else now_utc()
    new=base+timedelta(days=30*months); set_pro_until(update.effective_chat.id,new)
    safe_reply_private(update,context,f"✅ Pro kích hoạt đến {new.strftime('%d/%m/%Y %H:%M UTC')}")

# ================== EVENTS & MODERATION ==================
def message_handler(update,context):
    msg=update.message
    if not msg: return
    chat_id=msg.chat.id; user_id=msg.from_user.id
    s=get_setting(chat_id)
    wl=list_whitelist(chat_id); bl=list_blacklist(chat_id)
    txt=msg.text or msg.caption or ""

    # Blacklist ưu tiên
    if any(b.lower() in txt.lower() for b in bl):
        try: msg.delete()
        except Exception: pass
        return

    # Link & mention filter (Free)
    urls=URL_RE.findall(txt); mentions=MENTION_RE.findall(txt)
    if s["nolinks"]:
        if urls and not any(any(w.lower() in u.lower() for w in wl) for u in urls):
            try: msg.delete()
            except Exception: pass
            return
        if mentions:
            for m in mentions:
                if not any(w.lower() in m.lower() for w in wl):
                    try: msg.delete()
                    except Exception: pass
                    return

    # Forwards (Free)
    if s["noforwards"] and (msg.forward_date or msg.forward_from or msg.forward_from_chat):
        try: msg.delete()
        except Exception: pass
        return

    # Anti-flood (Pro)
    if s["antiflood"] and not is_admin(user_id):
        if not is_pro(chat_id):
            return
        if _is_flood(chat_id,user_id):
            try: msg.delete()
            except Exception: pass
            return

def delete_service_messages(update: Update, context: CallbackContext):
    # Ẩn các service message khi noevents=on
    if get_setting(update.effective_chat.id)["noevents"]:
        try:
            update.effective_message.delete()
        except Exception:
            pass

def on_new_members(update: Update, context: CallbackContext):
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
                    logger.warning("Kick bot fail: %s", e)

# ================== ERROR HANDLER ==================
def error_handler(update, context):
    err = context.error
    if isinstance(err, TimedOut):
        logger.warning("TimedOut từ Telegram, bỏ qua.")
        return
    if isinstance(err, NetworkError):
        logger.warning("NetworkError tạm thời, ngủ 1s rồi bỏ qua.")
        time.sleep(1)
        return
    logger.exception("Unhandled error: %s", err)

# ================== BOOT ==================
def start_bot():
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing"); return

    # Tăng độ chịu mạng chậm
    updater = Updater(
        BOT_TOKEN,
        use_context=True,
        request_kwargs={"read_timeout": 30, "connect_timeout": 30}
    )
    dp = updater.dispatcher

    # core
    dp.add_handler(CommandHandler("start",start))
    dp.add_handler(CommandHandler("help",help_cmd))
    dp.add_handler(CommandHandler("status",status))

    # toggles
    dp.add_handler(CommandHandler("nolinks",nolinks,pass_args=True))
    dp.add_handler(CommandHandler("noforwards",noforwards,pass_args=True))
    dp.add_handler(CommandHandler("nobots",nobots,pass_args=True))
    dp.add_handler(CommandHandler("antiflood",antiflood,pass_args=True))
    dp.add_handler(CommandHandler("noevents",noevents,pass_args=True))

    # lists
    dp.add_handler(CommandHandler("whitelist_add",whitelist_add_cmd,pass_args=True))
    dp.add_handler(CommandHandler("whitelist_remove",whitelist_remove_cmd,pass_args=True))
    dp.add_handler(CommandHandler("whitelist_list",whitelist_list_cmd))
    dp.add_handler(CommandHandler("blacklist_add",blacklist_add_cmd,pass_args=True))
    dp.add_handler(CommandHandler("blacklist_remove",blacklist_remove_cmd,pass_args=True))
    dp.add_handler(CommandHandler("blacklist_list",blacklist_list_cmd))

    # keys
    dp.add_handler(CommandHandler("genkey",genkey_cmd,pass_args=True))
    dp.add_handler(CommandHandler("keys_list",keys_list_cmd))
    dp.add_handler(CommandHandler("applykey",applykey_cmd,pass_args=True))

    # events
    dp.add_handler(MessageHandler(Filters.status_update, delete_service_messages))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, on_new_members))

    # messages
    dp.add_handler(MessageHandler(Filters.text | Filters.caption, message_handler))

    dp.add_error_handler(error_handler)

    logger.info("🚀 Starting polling… (drop_pending_updates=True)")
    updater.start_polling(drop_pending_updates=True, timeout=20, read_latency=2)
    updater.idle()

# ================== FLASK (Render keep-alive) ==================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ HotroSecurityBot is running (Render Free)."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Lưu ý: chỉ chạy 1 instance cho mỗi TOKEN, nếu không sẽ lỗi Conflict.
    t = threading.Thread(target=start_bot, daemon=True)
    t.start()
    run_flask()
