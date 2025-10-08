# HotroSecurityBot - Full (Render + PTB 13.15)
# - Private admin replies (DM) with graceful fallback
# - Free core + Pro lock + 7-day trial (/trial7)
# - Detailed /help (auto shows trial if available)
# - Fix common Telegram errors; safer polling on Render

import logging, os, re, sqlite3, threading, time, secrets
from collections import deque
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask

from telegram import Update, ParseMode
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, CallbackContext
)
from telegram.error import Forbidden, BadRequest, TimedOut

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
        pro_until TEXT NULL,
        trial_used INTEGER DEFAULT 0,
        trial_notified INTEGER DEFAULT 0
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

    # ensure columns (if nâng cấp)
    def ensure_col(table, col, type_sql):
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        if col not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_sql}")
            conn.commit()

    ensure_col("chat_settings", "trial_used", "INTEGER DEFAULT 0")
    ensure_col("chat_settings", "trial_notified", "INTEGER DEFAULT 0")
    ensure_col("chat_settings", "noevents", "INTEGER DEFAULT 0")
    ensure_col("chat_settings", "pro_until", "TEXT NULL")
    conn.close()

# ================== HELPERS ==================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def now_utc():
    return datetime.utcnow()

def safe_dm_or_hint(update: Update, context: CallbackContext, text: str, **kwargs):
    """
    Cố gắng nhắn riêng cho người gọi lệnh. Nếu bị Forbidden (chưa /start với bot),
    sẽ post 1 dòng gợi ý NGẮN trong nhóm và không crash.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try:
        context.bot.send_message(chat_id=user_id, text=text, **kwargs)
    except Forbidden:
        # nhắc rất ngắn trong nhóm, tránh lộ nội dung quản trị
        try:
            if update.effective_message:
                update.effective_message.reply_text(
                    "📩 Vui lòng mở chat riêng với bot (nhắn /start) để nhận hướng dẫn.",
                    disable_web_page_preview=True
                )
            else:
                context.bot.send_message(chat_id=chat_id,
                    text="📩 Vui lòng /start bot trong chat riêng để nhận hướng dẫn.")
        except Exception as e2:
            logger.warning("group hint failed: %s", e2)
    except BadRequest as e:
        logger.warning("safe_dm_or_hint BadRequest: %s", e)
    except Exception as e:
        logger.warning("safe_dm_or_hint error: %s", e)

def get_setting(chat_id: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT nolinks, noforwards, nobots, antiflood, noevents, pro_until,
                          trial_used, trial_notified
                   FROM chat_settings WHERE chat_id=?""", (chat_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO chat_settings(chat_id) VALUES(?)", (chat_id,))
        conn.commit()
        row = (1, 1, 1, 1, 0, None, 0, 0)
    conn.close()
    return {
        "nolinks": bool(row[0]),
        "noforwards": bool(row[1]),
        "nobots": bool(row[2]),
        "antiflood": bool(row[3]),
        "noevents": bool(row[4]),
        "pro_until": datetime.fromisoformat(row[5]) if row[5] else None,
        "trial_used": bool(row[6]),
        "trial_notified": bool(row[7]),
    }

def is_pro(chat_id: int) -> bool:
    s = get_setting(chat_id)
    return bool(s["pro_until"] and s["pro_until"] > now_utc())

def set_setting(chat_id: int, key: str, value):
    conn = _conn(); cur = conn.cursor()
    cur.execute(f"UPDATE chat_settings SET {key}=? WHERE chat_id=?", (value, chat_id))
    conn.commit(); conn.close()

def set_pro_until(chat_id: int, until_dt: datetime):
    conn = _conn(); cur = conn.cursor()
    cur.execute("UPDATE chat_settings SET pro_until=? WHERE chat_id=?", (until_dt.isoformat(), chat_id))
    conn.commit(); conn.close()

def mark_trial_used(chat_id: int):
    set_setting(chat_id, "trial_used", 1)

def mark_trial_notified(chat_id: int):
    set_setting(chat_id, "trial_notified", 1)

# ===== whitelist / blacklist (DB ops) =====
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

# ===== Pro keys =====
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

# ================== TEXTS ==================
def _help_text_free(trial_available: bool):
    trial_block = "🎁 *Dùng thử Pro 7 ngày (admin)*\n/trial7 – Kích hoạt dùng thử cho nhóm hiện tại (1 lần)\n" if trial_available else ""
    return f"""🛡 *HƯỚNG DẪN SỬ DỤNG (FREE)*

📍 *Chuẩn bị*
• Thêm bot vào nhóm và cấp quyền *Delete messages*.
• Nếu muốn nhận hướng dẫn qua DM, hãy /start với bot trong chat riêng.

📌 *Quản lý nhóm*
/status – Xem cấu hình & thời hạn Pro
/nolinks on|off – Chặn link & @mention
/noforwards on|off – Chặn tin forward
/nobots on|off – Cấm mời bot vào nhóm

📜 *Danh sách*
/whitelist_add <text> /whitelist_remove <text>
/whitelist_list
/blacklist_add <text> /blacklist_remove <text>
/blacklist_list

🧩 *Cách hoạt động*
• /nolinks on: xoá link/@mention (trừ whitelist)
• /noforwards on: xoá tin forward
• /blacklist_add: xoá ngay nếu chứa từ cấm

{trial_block}🔑 *Nâng cấp Pro*
/applykey <key> – Kích hoạt Pro
/genkey <tháng> – (Admin) tạo key dùng thử
/keys_list – (Admin) xem key

🛠 *Tiện ích*
/myid – Lấy user_id của bạn
/chatid – Lấy chat_id nhóm

💬 *Hỗ trợ:* @Myyduyenng
""".strip()

def _help_text_pro():
    return """💎 *HƯỚNG DẪN SỬ DỤNG (PRO)*

📌 *Quản lý nhóm*
/status – Xem cấu hình & thời hạn Pro
/nolinks on|off – Chặn link & @mention
/noforwards on|off – Chặn tin forward
/nobots on|off – Cấm mời bot vào nhóm
/noevents on|off – Ẩn join/leave
/antiflood on|off – Chống spam (3 tin / 20s)

📜 *Danh sách*
/whitelist_add <text> /whitelist_remove <text>
/whitelist_list
/blacklist_add <text> /blacklist_remove <text>
/blacklist_list

🧩 *Cách hoạt động*
• Link/mention bị chặn trừ whitelist
• Blacklist ưu tiên: phát hiện là xoá
• Anti-flood: >3 tin/20s bị xoá (trừ admin bot)
/noevents: Ẩn sự kiện join/leave

🔑 *Key*
/applykey <key> – Gia hạn/kích hoạt
/genkey <tháng> – (Admin) tạo key
/keys_list – (Admin) xem key

🛠 *Tiện ích*
/myid – User ID
/chatid – Chat ID

💬 *Hỗ trợ:* @Myyduyenng
""".strip()

# ================== COMMANDS ==================
def start(update, context):
    safe_dm_or_hint(update, context,
        "🤖 HotroSecurityBot đang hoạt động!\nGõ /help để xem hướng dẫn chi tiết.")

def help_cmd(update, context):
    chat = update.effective_chat
    user_id = update.effective_user.id

    # Chỉ admin (được khai báo trong ADMIN_IDS) mới xem help đầy đủ nếu gọi trong group
    if chat.type in ("group","supergroup") and not is_admin(user_id):
        return

    s = get_setting(chat.id)
    pro = is_pro(chat.id)
    text = _help_text_pro() if pro else _help_text_free(not s["trial_used"])
    safe_dm_or_hint(update, context, text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

def status(update, context):
    s = get_setting(update.effective_chat.id)
    wl=list_whitelist(update.effective_chat.id); bl=list_blacklist(update.effective_chat.id)
    pro_txt=f"⏳ Pro đến {s['pro_until'].strftime('%d/%m/%Y %H:%M UTC')}" if s["pro_until"] else "❌ Chưa có Pro"
    txt=(f"📋 Cấu hình:\n"
         f"nolinks={s['nolinks']} | noforwards={s['noforwards']} | nobots={s['nobots']} | "
         f"antiflood={s['antiflood']} | noevents={s['noevents']}\n{pro_txt}\n"
         f"Whitelist: {', '.join(wl) if wl else '(none)'}\n"
         f"Blacklist: {', '.join(bl) if bl else '(none)'}")
    safe_dm_or_hint(update, context, txt)

def _toggle(update,context,field,pro_only=False):
    if not is_admin(update.effective_user.id):
        safe_dm_or_hint(update,context,"❌ Bạn không phải admin.");return
    if pro_only and not is_pro(update.effective_chat.id):
        safe_dm_or_hint(update,context,f"🔒 {field} chỉ dành cho Pro.");return
    if not context.args or context.args[0].lower() not in ("on","off"):
        safe_dm_or_hint(update,context,f"Usage: /{field} on|off");return
    val=1 if context.args[0].lower()=="on" else 0
    set_setting(update.effective_chat.id,field,val)
    safe_dm_or_hint(update,context,f"✅ {field} = {'on' if val else 'off'}")

def nolinks(u,c): _toggle(u,c,"nolinks")
def noforwards(u,c): _toggle(u,c,"noforwards")
def nobots(u,c): _toggle(u,c,"nobots")
def antiflood(u,c): _toggle(u,c,"antiflood",pro_only=True)
def noevents(u,c): _toggle(u,c,"noevents",pro_only=True)

def myid(update, context):
    safe_dm_or_hint(update, context, f"👤 user_id của bạn: `{update.effective_user.id}`", parse_mode=ParseMode.MARKDOWN)

def chatid(update, context):
    safe_dm_or_hint(update, context, f"💬 chat_id hiện tại: `{update.effective_chat.id}`", parse_mode=ParseMode.MARKDOWN)

# ===== Trial 7 days =====
def trial7_cmd(update, context):
    chat_id = update.effective_chat.id
    if not is_admin(update.effective_user.id):
        safe_dm_or_hint(update, context, "❌ Bạn không phải admin."); return
    s = get_setting(chat_id)
    if s["trial_used"]:
        safe_dm_or_hint(update, context, "ℹ️ Nhóm này đã dùng thử Pro trước đó."); return
    base = s["pro_until"] if s["pro_until"] and s["pro_until"] > now_utc() else now_utc()
    new_until = base + timedelta(days=7)
    set_pro_until(chat_id, new_until)
    mark_trial_used(chat_id)
    safe_dm_or_hint(update, context, f"🎁 Đã kích hoạt Pro dùng thử 7 ngày đến {new_until.strftime('%d/%m/%Y %H:%M UTC')}.")

# ===== whitelist / blacklist commands =====
def whitelist_add_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_dm_or_hint(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_dm_or_hint(update,context,"Usage: /whitelist_add <text>"); return
    add_whitelist(update.effective_chat.id, " ".join(context.args).strip())
    safe_dm_or_hint(update,context,"✅ Đã thêm vào whitelist.")

def whitelist_remove_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_dm_or_hint(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_dm_or_hint(update,context,"Usage: /whitelist_remove <text>"); return
    remove_whitelist(update.effective_chat.id, " ".join(context.args).strip())
    safe_dm_or_hint(update,context,"✅ Đã xoá khỏi whitelist.")

def whitelist_list_cmd(update,context):
    wl = list_whitelist(update.effective_chat.id)
    safe_dm_or_hint(update,context,"📄 Whitelist:\n" + ("\n".join(wl) if wl else "(trống)"))

def blacklist_add_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_dm_or_hint(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_dm_or_hint(update,context,"Usage: /blacklist_add <text>"); return
    add_blacklist(update.effective_chat.id, " ".join(context.args).strip())
    safe_dm_or_hint(update,context,"✅ Đã thêm vào blacklist.")

def blacklist_remove_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_dm_or_hint(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_dm_or_hint(update,context,"Usage: /blacklist_remove <text>"); return
    remove_blacklist(update.effective_chat.id, " ".join(context.args).strip())
    safe_dm_or_hint(update,context,"✅ Đã xoá khỏi blacklist.")

def blacklist_list_cmd(update,context):
    bl = list_blacklist(update.effective_chat.id)
    safe_dm_or_hint(update,context,"📄 Blacklist:\n" + ("\n".join(bl) if bl else "(trống)"))

# ===== Keys =====
def genkey_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_dm_or_hint(update,context,"❌ Bạn không phải admin."); return
    months=1
    if context.args:
        try: months=int(context.args[0])
        except: safe_dm_or_hint(update,context,"Usage: /genkey <tháng>"); return
    k, exp = gen_key(months)
    safe_dm_or_hint(update,context,f"🔑 Key: `{k}`\nHiệu lực {months} tháng (tạo đến {exp.strftime('%d/%m/%Y %H:%M UTC')}).",
                    parse_mode=ParseMode.MARKDOWN)

def keys_list_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_dm_or_hint(update,context,"❌ Bạn không phải admin."); return
    rows = list_keys()
    if not rows:
        safe_dm_or_hint(update,context,"(Chưa có key)"); return
    out = ["🗝 Danh sách key:"]
    for k, m, c, e, u in rows:
        out.append(f"{k} | {m} tháng | tạo:{c} | hết hạn:{e} | used_by:{u}")
    safe_dm_or_hint(update,context,"\n".join(out))

def applykey_cmd(update,context):
    if not context.args:
        safe_dm_or_hint(update,context,"Usage: /applykey <key>");return
    ok,reason,months=consume_key(context.args[0].strip(),update.effective_user.id)
    if not ok:
        m={"invalid":"❌ Key sai","used":"❌ Key đã dùng","expired":"❌ Key hết hạn"}[reason]
        safe_dm_or_hint(update,context,m);return
    s=get_setting(update.effective_chat.id)
    base=s["pro_until"] if s["pro_until"] and s["pro_until"]>now_utc() else now_utc()
    new=base+timedelta(days=30*months); set_pro_until(update.effective_chat.id,new)
    safe_dm_or_hint(update,context,f"✅ Pro kích hoạt đến {new.strftime('%d/%m/%Y %H:%M UTC')}")

# ================== MESSAGE HANDLER ==================
def maybe_notify_trial_expired(update: Update, context: CallbackContext, s: dict):
    """Khi trial đã dùng và hết hạn, lần đầu admin tương tác sẽ nhận nhắc nhở."""
    chat_id = update.effective_chat.id
    if s["trial_used"] and not is_pro(chat_id) and not s["trial_notified"]:
        msg = ("⏰ *Dùng thử Pro đã kết thúc.*\n"
               "Bạn có thể kích hoạt lại Pro bằng `/applykey <key>`.")
        safe_dm_or_hint(update, context, msg, parse_mode=ParseMode.MARKDOWN)
        mark_trial_notified(chat_id)

def message_handler(update,context):
    msg=update.message
    if not msg: return
    chat_id=msg.chat.id; user_id=msg.from_user.id
    s=get_setting(chat_id)

    # check trial expiry notice
    if is_admin(user_id):
        maybe_notify_trial_expired(update, context, s)

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

# ================== BOOT ==================
def start_bot():
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing"); return
    updater=Updater(BOT_TOKEN, use_context=True)
    dp=updater.dispatcher

    # core
    dp.add_handler(CommandHandler("start",start))
    dp.add_handler(CommandHandler("help",help_cmd))
    dp.add_handler(CommandHandler("status",status))
    dp.add_handler(CommandHandler("myid",myid))
    dp.add_handler(CommandHandler("chatid",chatid))

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

    # keys & trial
    dp.add_handler(CommandHandler("genkey",genkey_cmd,pass_args=True))
    dp.add_handler(CommandHandler("keys_list",keys_list_cmd))
    dp.add_handler(CommandHandler("applykey",applykey_cmd,pass_args=True))
    dp.add_handler(CommandHandler("trial7",trial7_cmd))

    # messages
    dp.add_handler(MessageHandler(Filters.text | Filters.caption, message_handler))

    logger.info("🚀 Bot starting polling...")
    # drop_pending_updates giảm lỗi Conflict khi redeploy
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

# ================== FLASK (Render keep-alive) ==================
flask_app=Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ HotroSecurityBot running (Render Free)."

def run_flask():
    port=int(os.environ.get("PORT",10000))
    flask_app.run(host="0.0.0.0",port=port)

if __name__=="__main__":
    t=threading.Thread(target=start_bot,daemon=True)
    t.start()
    run_flask()
