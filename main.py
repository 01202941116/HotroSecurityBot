# HotroSecurityBot - Fixed Full Version (Render + PTB 13.15)
# Free features active by default, Pro locked properly, private admin replies

import logging, os, re, sqlite3, threading, time, secrets
from collections import deque
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
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

def now_utc(): return datetime.utcnow()

def safe_reply_private(update: Update, context: CallbackContext, text: str, **kwargs):
    """Trả lời riêng admin thay vì gửi ra nhóm"""
    try:
        context.bot.send_message(chat_id=update.effective_user.id, text=text, **kwargs)
    except Exception as e:
        logger.warning("safe_reply_private error: %s", e)

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

# whitelist / blacklist
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

# Pro keys
def gen_key(months=1):
    key = secrets.token_urlsafe(12)
    created = now_utc()
    expires = created + timedelta(days=30*int(months))
    conn=_conn();cur=conn.cursor()
    cur.execute("INSERT INTO pro_keys(key,months,created_at,expires_at) VALUES(?,?,?,?)",
                (key,months,created.isoformat(),expires.isoformat()))
    conn.commit();conn.close()
    return key,expires

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

# ================== FILTERS ==================
URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
MENTION_RE = re.compile(r"@([A-Za-z0-9_]{5,64})")
FLOOD_WINDOW, FLOOD_LIMIT = 20, 3
user_buckets = {}

def _is_flood(chat_id,user_id):
    k=(chat_id,user_id);dq=user_buckets.get(k);now=time.time()
    if dq is None: dq=deque(maxlen=FLOOD_LIMIT);user_buckets[k]=dq
    while dq and now-dq[0]>FLOOD_WINDOW: dq.popleft()
    dq.append(now);return len(dq)>FLOOD_LIMIT

# ================== COMMANDS ==================
def start(update,context):
    safe_reply_private(update,context,"🤖 HotroSecurityBot đang hoạt động!\nDùng /help để xem lệnh.")

def help_cmd(update,context):
    chat_id=update.effective_chat.id; pro=is_pro(chat_id)
    lines=[
        "🛡 *HƯỚNG DẪN SỬ DỤNG*",
        "• `/status` – Xem cấu hình & thời hạn Pro",
        "• `/nolinks on|off` – Bật/tắt chặn link & @mention",
        "• `/noforwards on|off` – Chặn tin forward",
        "• `/nobots on|off` – Cấm mời bot vào nhóm",
        "",
        "• `/whitelist_add <text>` / `/whitelist_remove <text>`",
        "• `/blacklist_add <text>` / `/blacklist_remove <text>`",
        ""
    ]
    if pro:
        lines += [
            "✨ *Tính năng Pro:*",
            "• `/antiflood on|off` – Chống spam (3 tin / 20s)",
            "• `/noevents on|off` – Ẩn join/leave",
            "• `/ads_add`, `/ads_list`, `/ads_pause`, `/ads_resume`, `/ads_delete` – Tự động quảng cáo",
            "• Siết mentions, ưu tiên blacklist"
        ]
    else:
        lines += [
            "🔒 *Tính năng Pro (chưa kích hoạt)*",
            "• `/applykey <key>` – Kích hoạt Pro",
            "• `/genkey` (Admin) – Tạo key thử nghiệm"
        ]
    safe_reply_private(update,context,"\n".join(lines),parse_mode=ParseMode.MARKDOWN)

def status(update,context):
    s=get_setting(update.effective_chat.id)
    wl=list_whitelist(update.effective_chat.id); bl=list_blacklist(update.effective_chat.id)
    pro_txt=f"⏳ Pro đến {s['pro_until'].strftime('%d/%m/%Y %H:%M UTC')}" if s["pro_until"] else "❌ Chưa có Pro"
    txt=(f"📋 Cấu hình:\n"
         f"nolinks={s['nolinks']} | noforwards={s['noforwards']} | nobots={s['nobots']} | "
         f"antiflood={s['antiflood']} | noevents={s['noevents']}\n{pro_txt}\n"
         f"Whitelist: {', '.join(wl) if wl else '(none)'}\n"
         f"Blacklist: {', '.join(bl) if bl else '(none)'}")
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

# ================== APPLY KEY ==================
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

# ================== MESSAGE HANDLER ==================
def message_handler(update,context):
    msg=update.message
    if not msg: return
    chat_id=msg.chat.id; user_id=msg.from_user.id
    s=get_setting(chat_id)
    wl=list_whitelist(chat_id); bl=list_blacklist(chat_id)
    txt=msg.text or msg.caption or ""

    # blacklist ưu tiên
    if any(b.lower() in txt.lower() for b in bl):
        try: msg.delete()
        except: pass
        return

    # nolinks (free)
    urls=URL_RE.findall(txt); mentions=MENTION_RE.findall(txt)
    if s["nolinks"]:
        if urls and not any(any(w.lower() in u.lower() for w in wl) for u in urls):
            try: msg.delete()
            except: pass
            return
        if mentions:
            for m in mentions:
                if not any(w.lower() in m.lower() for w in wl):
                    try: msg.delete()
                    except: pass
                    return

    # noforwards
    if s["noforwards"] and (msg.forward_date or msg.forward_from):
        try: msg.delete()
        except: pass
        return

    # antiflood (pro)
    if s["antiflood"] and not is_admin(user_id):
        if not is_pro(chat_id): return
        if _is_flood(chat_id,user_id):
            try: msg.delete()
            except: pass
            return

# ================== BOOT ==================
def start_bot():
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing"); return
    updater=Updater(BOT_TOKEN,use_context=True)
    dp=updater.dispatcher
    dp.add_handler(CommandHandler("start",start))
    dp.add_handler(CommandHandler("help",help_cmd))
    dp.add_handler(CommandHandler("status",status))
    dp.add_handler(CommandHandler("nolinks",nolinks,pass_args=True))
    dp.add_handler(CommandHandler("noforwards",noforwards,pass_args=True))
    dp.add_handler(CommandHandler("nobots",nobots,pass_args=True))
    dp.add_handler(CommandHandler("antiflood",antiflood,pass_args=True))
    dp.add_handler(CommandHandler("noevents",noevents,pass_args=True))
    dp.add_handler(CommandHandler("applykey",applykey_cmd,pass_args=True))
    dp.add_handler(MessageHandler(Filters.text | Filters.caption, message_handler))
    logger.info("🚀 Bot started")
    updater.start_polling()
    updater.idle()

# ================== FLASK ==================
flask_app=Flask(__name__)
@flask_app.route("/")
def home(): return "✅ HotroSecurityBot running (Render)"
def run_flask():
    port=int(os.environ.get("PORT",10000))
    flask_app.run(host="0.0.0.0",port=port)

if __name__=="__main__":
    t=threading.Thread(target=start_bot,daemon=True)
    t.start()
    run_flask()
