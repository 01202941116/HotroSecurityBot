# HotroSecurityBot – Render + PTB 13.15
# - Admin-only replies (DM first, fallback in group)
# - Free features + Pro features (with 7-day trial /trial7)
# - Admin bypass for filters
# - Auto Pro expiry notice (DM admin; fallback announce)
# - Flask keep-alive + polling in background

import logging, os, re, sqlite3, threading, time, secrets
from collections import deque
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask
from telegram import Update, ParseMode
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, CallbackContext, JobQueue
)

# ================== ENV / LOG ==================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("HotroSecurityBot")

DB = "hotrosecurity.db"

# ================== DB ==================
def _conn():
    return sqlite3.connect(DB)

def _ensure_col(cur, col, type_sql):
    cur.execute("PRAGMA table_info(chat_settings)")
    cols = [r[1] for r in cur.fetchall()]
    if col not in cols:
        cur.execute(f"ALTER TABLE chat_settings ADD COLUMN {col} {type_sql}")

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
        last_pro_notice TEXT NULL
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
    # ensure new columns when deploy upgrade
    _ensure_col(cur, "trial_used", "INTEGER DEFAULT 0")
    _ensure_col(cur, "last_pro_notice", "TEXT NULL")
    conn.commit(); conn.close()

# ================== HELPERS ==================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def now_utc(): 
    return datetime.utcnow()

def safe_reply_private(update: Update, context: CallbackContext, text: str, **kwargs):
    """
    Ưu tiên gửi DM cho người gọi lệnh (admin).
    Nếu Telegram cấm (user chưa /start bot ở DM), fallback trả lời tối thiểu trong group.
    """
    user_id = update.effective_user.id if update and update.effective_user else None
    chat_id = update.effective_chat.id if update and update.effective_chat else None
    try:
        if user_id:
            context.bot.send_message(chat_id=user_id, text=text, **kwargs)
            return
    except Exception as e:
        # Forbidden: bot can't initiate conversation with a user
        logger.warning("safe_reply_private: DM failed -> %s", e)

    # fallback gửi trong group (nếu có), nhắc user /start bot ở DM
    try:
        if chat_id:
            context.bot.send_message(
                chat_id=chat_id,
                text="(🔔 Chỉ báo cho admin) " + text + "\n\nℹ️ Nếu muốn nhận tin riêng, hãy mở DM với bot và gửi /start.",
                **{k:v for k,v in kwargs.items() if k != "reply_markup"}  # tránh inline markup rò rỉ
            )
    except Exception as e2:
        logger.warning("safe_reply_private: group fallback failed -> %s", e2)

def get_setting(chat_id: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT nolinks, noforwards, nobots, antiflood, noevents, pro_until, trial_used, last_pro_notice
                   FROM chat_settings WHERE chat_id=?""", (chat_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO chat_settings(chat_id) VALUES(?)", (chat_id,))
        conn.commit()
        row = (1, 1, 1, 1, 0, None, 0, None)
    conn.close()
    return {
        "nolinks": bool(row[0]),
        "noforwards": bool(row[1]),
        "nobots": bool(row[2]),
        "antiflood": bool(row[3]),
        "noevents": bool(row[4]),
        "pro_until": datetime.fromisoformat(row[5]) if row[5] else None,
        "trial_used": bool(row[6]),
        "last_pro_notice": datetime.fromisoformat(row[7]) if row[7] else None
    }

def set_setting(chat_id: int, key: str, value):
    conn = _conn(); cur = conn.cursor()
    cur.execute(f"UPDATE chat_settings SET {key}=? WHERE chat_id=?", (value, chat_id))
    conn.commit(); conn.close()

def set_pro_until(chat_id: int, until_dt: datetime):
    set_setting(chat_id, "pro_until", until_dt.isoformat())

def set_trial_used(chat_id: int, used: bool):
    set_setting(chat_id, "trial_used", 1 if used else 0)

def set_last_pro_notice(chat_id: int, dt: datetime):
    set_setting(chat_id, "last_pro_notice", dt.isoformat() if dt else None)

def is_pro(chat_id: int) -> bool:
    s = get_setting(chat_id)
    return bool(s["pro_until"] and s["pro_until"] > now_utc())

# whitelist/blacklist ops
def add_whitelist(chat_id, text):
    conn=_conn();cur=conn.cursor()
    cur.execute("INSERT INTO whitelist(chat_id,text) VALUES(?,?)",(chat_id,text.strip()))
    conn.commit();conn.close()

def remove_whitelist(chat_id, text):
    conn=_conn();cur=conn.cursor()
    cur.execute("DELETE FROM whitelist WHERE chat_id=? AND text=?",(chat_id,text.strip()))
    conn.commit();conn.close()

def list_whitelist(chat_id):
    conn=_conn();cur=conn.cursor()
    cur.execute("SELECT text FROM whitelist WHERE chat_id=?",(chat_id,))
    r=[x[0] for x in cur.fetchall()];conn.close();return r

def add_blacklist(chat_id,text):
    conn=_conn();cur=conn.cursor()
    cur.execute("INSERT INTO blacklist(chat_id,text) VALUES(?,?)",(chat_id,text.strip()))
    conn.commit();conn.close()

def remove_blacklist(chat_id,text):
    conn=_conn();cur=conn.cursor()
    cur.execute("DELETE FROM blacklist WHERE chat_id=? AND text=?",(chat_id,text.strip()))
    conn.commit();conn.close()

def list_blacklist(chat_id):
    conn=_conn();cur=conn.cursor()
    cur.execute("SELECT text FROM blacklist WHERE chat_id=?",(chat_id,))
    r=[x[0] for x in cur.fetchall()];conn.close();return r

# Pro keys (tuỳ chọn, vẫn giữ)
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

# ================== FILTERS / STATE ==================
URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
MENTION_RE = re.compile(r"@([A-Za-z0-9_]{5,64})")
# Bắt domain trần và IPv4 (không cần http/https)
DOMAIN_RE = re.compile(
    r"\b((?:[a-z0-9-]{1,63}\.)+(?:[a-z]{2,}|xn--[a-z0-9-]{2,}))\b(?:[/:?&#][^\s]*)?",
    re.IGNORECASE,
)
IPV4_RE = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:[/?#][^\s]*)?\b",
    re.IGNORECASE,
)

def extract_links(msg):
    """
    Lấy tất cả link trong message:
    - Từ Telegram entities (URL, TEXT_LINK)
    - Từ regex domain trần & IPv4
    Trả về list[str] (đã loại trùng, giữ nguyên text gốc).
    """
    text = msg.text or msg.caption or ""
    found = []

    # 1) Entities do Telegram phân tích (ổn định nhất)
    entities = []
    if msg.entities:
        entities.extend(msg.entities)
    if msg.caption_entities:
        entities.extend(msg.caption_entities)

    for ent in entities:
        t = ent.type
        if t == "text_link" and getattr(ent, "url", None):
            found.append(ent.url)
        elif t in ("url", "mention", "email"):  # url là chính; mention/email tùy bạn có muốn chặn
            try:
                # Lấy đoạn text khớp entity
                start = ent.offset
                end = ent.offset + ent.length
                found.append(text[start:end])
            except Exception:
                pass

    # 2) Regex cho domain trần & IPv4 (phòng khi client không tạo entity)
    found.extend(DOMAIN_RE.findall(text))
    found.extend(IPV4_RE.findall(text))

    # Chuẩn hóa & loại trùng
    # Với DOMAIN_RE/IPV4_RE, .findall trả về group -> đã là chuỗi
    # Giữ nguyên letter-case để đối chiếu whitelist theo cách hiện tại (bạn đang .lower() khi so)
    uniq = []
    seen = set()
    for u in found:
        u_strip = u.strip()
        if u_strip and u_strip.lower() not in seen:
            uniq.append(u_strip)
            seen.add(u_strip.lower())
    return uniq

FLOOD_WINDOW, FLOOD_LIMIT = 20, 3
user_buckets = {}

def _is_flood(chat_id, user_id):
    k=(chat_id,user_id);dq=user_buckets.get(k);now=time.time()
    if dq is None: dq=deque(maxlen=FLOOD_LIMIT);user_buckets[k]=dq
    while dq and now-dq[0]>FLOOD_WINDOW: dq.popleft()
    dq.append(now);return len(dq)>FLOOD_LIMIT

# ================== COMMANDS ==================
def start(update: Update, context: CallbackContext):
    safe_reply_private(update, context,
        "🤖 HotroSecurityBot đang hoạt động!\nGõ /help để xem hướng dẫn chi tiết."
    )

def myid_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id if update.effective_user else None
    safe_reply_private(update, context, f"🆔 Your user_id: `{uid}`", parse_mode=ParseMode.MARKDOWN)

def chatid_cmd(update: Update, context: CallbackContext):
    cid = update.effective_chat.id if update.effective_chat else None
    safe_reply_private(update, context, f"💬 This chat_id: `{cid}`", parse_mode=ParseMode.MARKDOWN)

def _help_text_free():
    return """🛡 *HƯỚNG DẪN SỬ DỤNG CƠ BẢN*

ℹ️ *Lưu ý:* Gõ `/help` trong group chỉ admin mới nhận hướng dẫn chi tiết qua DM.

🚀 *Bắt đầu*
• Thêm bot vào nhóm → cấp quyền xoá tin nhắn.
• Mở DM với bot và gửi `/start` để nhận thông báo riêng (DM).

📌 *Quản lý nhóm*
• `/status`
  → Xem cấu hình hiện tại, hạn Pro, whitelist/blacklist của nhóm.

• `/nolinks on|off`
  → Bật/tắt *chặn link & @mention*.
  Ví dụ: `/nolinks on`
  ✅ Muốn *cho phép một link/mention cụ thể* thì thêm vào whitelist (xem mục “Danh sách”).

• `/noforwards on|off`
  → Chặn tin nhắn được *forward* vào nhóm.
  Ví dụ: `/noforwards on`

• `/nobots on|off`
  → Cấm thành viên *mời thêm bot* vào nhóm (bật/tắt cờ kiểm soát này).

📜 *Danh sách (cho phép/chặn theo từ khoá)*
• `/whitelist_add <text>`
  → Cho phép <text> bỏ qua chặn (áp dụng cho *link/mention/từ khoá*).
  Ví dụ:
  - `/whitelist_add youtube.com`  (cho phép link youtube)
  - `/whitelist_add @myshop`      (cho phép mention @myshop)
  - `/whitelist_add khuyen mai`   (cho phép cụm từ “khuyen mai”)

• `/whitelist_remove <text>`  → Xoá khỏi whitelist
• `/whitelist_list`           → Xem toàn bộ whitelist

• `/blacklist_add <text>`
  → Nếu *từ khoá/chuỗi* xuất hiện trong tin nhắn, bot sẽ xoá ngay.
  Ví dụ:
  - `/blacklist_add cờ bạc`
  - `/blacklist_add lô đề`
  - `/blacklist_add spamdomain.com`

• `/blacklist_remove <text>` → Xoá khỏi blacklist
• `/blacklist_list`          → Xem toàn bộ blacklist

🧪 *Dùng thử Pro 7 ngày (chỉ admin)* 
• `/trial7`
  → Kích hoạt *Pro dùng thử* cho *nhóm hiện tại* trong 7 ngày (chỉ 1 lần/nhóm).
  Khi hết hạn, bot tự tắt các tính năng Pro và nhắc trong nhóm.

🔑 *Nâng cấp bằng key*
• `/applykey <key>`  → Kích hoạt/gia hạn Pro bằng key
• `/genkey <tháng>`  → *(Admin)* tạo key thử nghiệm nhanh. Ví dụ: `/genkey 1`
""".strip()

def _help_text_pro():
    return """💎 *HOTRO SECURITY PRO – ĐÃ KÍCH HOẠT*

⚙️ *Cài đặt chính*
• `/status`              → Xem cấu hình nhóm & hạn Pro
• `/nolinks on|off`      → Chặn link & @mention (kết hợp whitelist)
• `/noforwards on|off`   → Chặn tin nhắn forward
• `/nobots on|off`       → Cấm mời thêm bot vào nhóm
• `/noevents on|off`     → Ẩn join/leave message trong nhóm
• `/antiflood on|off`    → Chống spam: *xoá khi >3 tin/20s/người*
   Ví dụ: `/antiflood on`

📜 *Danh sách*
• `/whitelist_add <text>`  /  `/whitelist_remove <text>`  /  `/whitelist_list`
   Ví dụ:
   - `/whitelist_add t.me/mychannel`
   - `/whitelist_add @brand_official`
• `/blacklist_add <text>`   /  `/blacklist_remove <text>`  /  `/blacklist_list`
   Ví dụ:
   - `/blacklist_add tuyển CTV`
   - `/blacklist_add scamdomain.xyz`

🔑 *Quản lý key*
• `/applykey <key>`  → Kích hoạt hoặc gia hạn Pro
• `/genkey <tháng>`  → *(Admin)* tạo key dùng thử. Ví dụ: `/genkey 3`
• `/keys_list`       → *(Admin)* xem danh sách key hiện có

🧭 *Quy tắc hoạt động*
• Admin *không bị chặn* bởi các bộ lọc (bypass).
• *Blacklist ưu tiên:* nếu khớp, tin sẽ bị xoá ngay cả khi link/mention đã bật.
• *Whitelist chỉ định:* cho phép các link/mention/từ khoá cụ thể vượt qua bộ lọc.
""".strip()

def help_cmd(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user_id = update.effective_user.id
    # chỉ admin mới nhận help chi tiết khi gọi trong group (và qua DM trước)
    if chat.type in ("group","supergroup") and not is_admin(user_id):
        return
    pro = is_pro(chat.id)
    text = _help_text_pro() if pro else _help_text_free()
    safe_reply_private(update, context, text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

def status(update: Update, context: CallbackContext):
    s=get_setting(update.effective_chat.id)
    wl=list_whitelist(update.effective_chat.id); bl=list_blacklist(update.effective_chat.id)
    pro_txt=f"⏳ Pro đến {s['pro_until'].strftime('%d/%m/%Y %H:%M UTC')}" if s["pro_until"] else "❌ Chưa có Pro"
    txt=(f"📋 Cấu hình:\n"
         f"nolinks={s['nolinks']} | noforwards={s['noforwards']} | nobots={s['nobots']} | "
         f"antiflood={s['antiflood']} | noevents={s['noevents']}\n{pro_txt}\n"
         f"Whitelist: {', '.join(wl) if wl else '(none)'}\n"
         f"Blacklist: {', '.join(bl) if bl else '(none)'}")
    safe_reply_private(update,context,txt)

def _toggle(update: Update, context: CallbackContext, field: str, pro=False):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update, context, "❌ Bạn không phải admin.");return
    if pro and not is_pro(update.effective_chat.id):
        safe_reply_private(update, context, f"🔒 {field} chỉ dành cho Pro.");return
    if not context.args or context.args[0].lower() not in ("on","off"):
        safe_reply_private(update, context, f"Usage: /{field} on|off");return
    val=1 if context.args[0].lower()=="on" else 0
    set_setting(update.effective_chat.id, field, val)
    safe_reply_private(update, context, f"✅ {field} = {'on' if val else 'off'}")

def nolinks(u,c): _toggle(u,c,"nolinks")
def noforwards(u,c): _toggle(u,c,"noforwards")
def nobots(u,c): _toggle(u,c,"nobots")
def antiflood(u,c): _toggle(u,c,"antiflood",pro=True)
def noevents(u,c): _toggle(u,c,"noevents",pro=True)

# ----- WHITELIST / BLACKLIST -----
def whitelist_add_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_reply_private(update,context,"Usage: /whitelist_add <text>"); return
    add_whitelist(update.effective_chat.id, " ".join(context.args))
    safe_reply_private(update,context,"✅ Đã thêm vào whitelist.")

def whitelist_remove_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_reply_private(update,context,"Usage: /whitelist_remove <text>"); return
    remove_whitelist(update.effective_chat.id, " ".join(context.args))
    safe_reply_private(update,context,"✅ Đã xoá khỏi whitelist.")

def whitelist_list_cmd(update,context):
    wl = list_whitelist(update.effective_chat.id)
    safe_reply_private(update,context,"📄 Whitelist:\n" + ("\n".join(wl) if wl else "(trống)"))

def blacklist_add_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_reply_private(update,context,"Usage: /blacklist_add <text>"); return
    add_blacklist(update.effective_chat.id, " ".join(context.args))
    safe_reply_private(update,context,"✅ Đã thêm vào blacklist.")

def blacklist_remove_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    if not context.args:
        safe_reply_private(update,context,"Usage: /blacklist_remove <text>"); return
    remove_blacklist(update.effective_chat.id, " ".join(context.args))
    safe_reply_private(update,context,"✅ Đã xoá khỏi blacklist.")

def blacklist_list_cmd(update,context):
    bl = list_blacklist(update.effective_chat.id)
    safe_reply_private(update,context,"📄 Blacklist:\n" + ("\n".join(bl) if bl else "(trống)"))

# ----- KEY CMDS -----
def genkey_cmd(update,context):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update,context,"❌ Bạn không phải admin."); return
    months = 1
    if context.args:
        try: months = int(context.args[0])
        except: 
            safe_reply_private(update,context,"Usage: /genkey <tháng>"); return
    k, exp = gen_key(months)
    safe_reply_private(update,context,f"🔑 Key: `{k}`\nHiệu lực {months} tháng (tạo đến {exp.strftime('%d/%m/%Y %H:%M UTC')}).",
                       parse_mode=ParseMode.MARKDOWN)

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

# ----- TRIAL 7 DAYS -----
def trial7_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        safe_reply_private(update, context, "❌ Chỉ admin mới kích hoạt dùng thử.")
        return

    # Mặc định: nhóm hiện tại
    target_chat_id = update.effective_chat.id

    # Cho phép dùng trong DM: /trial7 <chat_id>
    if update.effective_chat.type == "private" and not context.args:
        safe_reply_private(
            update, context,
            "ℹ️ Bạn đang dùng trong DM.\n"
            "• Cách 1: vào nhóm rồi gõ /trial7\n"
            "• Cách 2: gõ `/trial7 <chat_id>` để bật cho nhóm cụ thể.\n"
            "Dùng /chatid trong nhóm để lấy chat_id.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if context.args:
        try:
            target_chat_id = int(context.args[0])
        except Exception:
            safe_reply_private(update, context, "Usage: /trial7 [chat_id]\nVí dụ: /trial7 -1001234567890")
            return

    s = get_setting(target_chat_id)
    if s["trial_used"]:
        safe_reply_private(update, context, "ℹ️ Nhóm này đã dùng thử trước đó.")
        return
    if is_pro(target_chat_id):
        safe_reply_private(update, context, "ℹ️ Nhóm đang ở trạng thái Pro rồi.")
        return

    until = now_utc() + timedelta(days=7)
    set_pro_until(target_chat_id, until)
    set_trial_used(target_chat_id, True)

    where_txt = "nhóm hiện tại" if target_chat_id == update.effective_chat.id else f"chat_id {target_chat_id}"
    safe_reply_private(
        update, context,
        f"🎁 Đã kích hoạt *Pro dùng thử 7 ngày* cho {where_txt} đến {until.strftime('%d/%m/%Y %H:%M UTC')}.",
        parse_mode=ParseMode.MARKDOWN
    )
# ----- SCHEDULER: kiểm tra hết hạn Pro mỗi 30 phút -----
def pro_expiry_check(context: CallbackContext):
    try:
        # Duyệt tất cả chat có cấu hình
        conn=_conn();cur=conn.cursor()
        cur.execute("SELECT chat_id, pro_until, last_pro_notice FROM chat_settings")
        rows = cur.fetchall(); conn.close()
        for chat_id, pro_until, last_notice in rows:
            if not pro_until:
                continue
            pro_dt = datetime.fromisoformat(pro_until)
            if pro_dt > now_utc():
                # reset last notice nếu còn hạn
                if last_notice:
                    set_last_pro_notice(chat_id, None)
                continue
            # Pro hết hạn -> set None & thông báo 1 lần
            if not last_notice:
                set_pro_until(chat_id, now_utc() - timedelta(seconds=1))  # đảm bảo is_pro False
                set_last_pro_notice(chat_id, now_utc())
                # DM admin (nếu có), fallback group
                msg = ("⛔ Gói Pro của nhóm đã *hết hạn dùng thử/keys*.\n"
                       "Vui lòng liên hệ admin để gia hạn hoặc dùng /applykey <key>.")
                try:
                    # gửi vào nhóm (tối thiểu) vì có thể không biết admin nào đã /start
                    context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logger.warning("Notify expiry failed for %s: %s", chat_id, e)
    except Exception as e:
        logger.error("pro_expiry_check error: %s", e)

# ================== MESSAGE HANDLER ==================
DOMAIN_RE = re.compile(
    r"\b((?:[a-z0-9-]{1,63}\.)+(?:[a-z]{2,}|xn--[a-z0-9-]{2,}))\b(?:[/:?&#][^\s]*)?",
    re.IGNORECASE,
)
IPV4_RE = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:[/?#][^\s]*)?\b",
    re.IGNORECASE,
)

def extract_links(msg):
    """
    Lấy tất cả link trong message:
    - Từ Telegram entities (URL, TEXT_LINK)
    - Từ regex domain trần & IPv4
    """
    text = msg.text or msg.caption or ""
    found = []

    # 1️⃣ Entities do Telegram tự nhận diện
    entities = []
    if msg.entities:
        entities.extend(msg.entities)
    if msg.caption_entities:
        entities.extend(msg.caption_entities)

    for ent in entities:
        t = ent.type
        if t == "text_link" and getattr(ent, "url", None):
            found.append(ent.url)
        elif t in ("url", "mention", "email"):
            try:
                start = ent.offset
                end = ent.offset + ent.length
                found.append(text[start:end])
            except Exception:
                pass

    # 2️⃣ Regex cho domain trần & IPv4
    found.extend(DOMAIN_RE.findall(text))
    found.extend(IPV4_RE.findall(text))

    # 3️⃣ Loại trùng
    uniq = []
    seen = set()
    for u in found:
        u_strip = u.strip()
        if u_strip and u_strip.lower() not in seen:
            uniq.append(u_strip)
            seen.add(u_strip.lower())
    return uniq


def message_handler(update, context):
    msg = update.message
    if not msg:
        return

    chat_id = msg.chat.id
    user_id = msg.from_user.id
    s = get_setting(chat_id)
    wl = list_whitelist(chat_id)
    bl = list_blacklist(chat_id)
    txt = msg.text or msg.caption or ""

    # ----- Admin bypass -----
    if is_admin(user_id):
        # Nếu muốn blacklist vẫn áp cho admin, bỏ comment 3 dòng dưới:
        # if any(b.lower() in txt.lower() for b in bl):
        #     try: msg.delete()
        #     except: pass
        return

    # ----- Blacklist ưu tiên -----
    if any(b.lower() in txt.lower() for b in bl):
        try:
            msg.delete()
        except:
            pass
        return

    # ----- Link & mentions (Free) -----
    mentions = MENTION_RE.findall(txt)
    urls = extract_links(msg)  # 👈 dùng hàm mới để bắt cả domain trần

    if s["nolinks"]:
        if urls:
            allowed = False
            if wl:
                for u in urls:
                    if any(w.lower() in u.lower() for w in wl):
                        allowed = True
                        break
            if not allowed:
                try:
                    msg.delete()
                except:
                    pass
                return

        if mentions:
            for m in mentions:
                if not any(w.lower() in m.lower() for w in wl):
                    try:
                        msg.delete()
                    except:
                        pass
                    return

    # ----- Forwards (Free) -----
    if s["noforwards"] and (
        msg.forward_date or msg.forward_from or msg.forward_from_chat
    ):
        try:
            msg.delete()
        except:
            pass
        return

    # ----- Anti-flood (Pro) -----
    if s["antiflood"]:
        if not is_pro(chat_id):
            return
        if _is_flood(chat_id, user_id):
            try:
                msg.delete()
            except:
                pass
            return

# ================== BOOT ==================
def start_bot():
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing")
        return

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # ✅ FIX: xóa webhook cũ trước khi polling để tránh lỗi Conflict
    try:
        updater.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared successfully before polling.")
    except Exception as e:
        logger.warning(f"Failed to delete webhook: {e}")

    # core
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("myid", myid_cmd))
    dp.add_handler(CommandHandler("chatid", chatid_cmd))

    # toggles
    dp.add_handler(CommandHandler("nolinks", nolinks, pass_args=True))
    dp.add_handler(CommandHandler("noforwards", noforwards, pass_args=True))
    dp.add_handler(CommandHandler("nobots", nobots, pass_args=True))
    dp.add_handler(CommandHandler("antiflood", antiflood, pass_args=True))
    dp.add_handler(CommandHandler("noevents", noevents, pass_args=True))

    # lists
    dp.add_handler(CommandHandler("whitelist_add", whitelist_add_cmd, pass_args=True))
    dp.add_handler(CommandHandler("whitelist_remove", whitelist_remove_cmd, pass_args=True))
    dp.add_handler(CommandHandler("whitelist_list", whitelist_list_cmd))
    dp.add_handler(CommandHandler("blacklist_add", blacklist_add_cmd, pass_args=True))
    dp.add_handler(CommandHandler("blacklist_remove", blacklist_remove_cmd, pass_args=True))
    dp.add_handler(CommandHandler("blacklist_list", blacklist_list_cmd))

    # key + trial
    dp.add_handler(CommandHandler("genkey", genkey_cmd, pass_args=True))
    dp.add_handler(CommandHandler("keys_list", keys_list_cmd))
    dp.add_handler(CommandHandler("applykey", applykey_cmd, pass_args=True))
    dp.add_handler(CommandHandler("trial7", trial7_cmd))

    # messages
    dp.add_handler(MessageHandler(Filters.text | Filters.caption, message_handler))

    # scheduler: check pro expiry each 30 minutes
    jobq: JobQueue = updater.job_queue
    jobq.run_repeating(pro_expiry_check, interval=30 * 60, first=60)

    logger.info("🚀 Bot polling...")
    try:
        updater.start_polling(drop_pending_updates=True, timeout=20)
    except Exception as e:
        logger.error(f"start_polling error (possible concurrent instance): {e}")
        raise

    updater.idle()

# ================== FLASK (Render keep-alive) ==================
flask_app=Flask(__name__)

@flask_app.route("/")
def home(): 
    return "✅ HotroSecurityBot running (Render Free) – OK"

def run_flask():
    port=int(os.environ.get("PORT",10000))
    # Debug off vì Render log đã có
    flask_app.run(host="0.0.0.0",port=port)

# ================== RUN ==================
if __name__=="__main__":
    t=threading.Thread(target=start_bot,daemon=True)
    t.start()
    run_flask()
