# -*- coding: utf-8 -*-
# HotroSecurityBot – PTB 20 + Flask (Render friendly)
# Giữ nguyên cấu trúc & tính năng, chỉ sửa lỗi và nâng cấp PTB20.

import logging, os, re, sqlite3, threading, time, secrets
from collections import deque
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask

from telegram import Update
from telegram.constants import ParseMode, ChatType
from telegram.ext import (
    ApplicationBuilder, Application, CommandHandler, MessageHandler,
    ContextTypes, JobQueue, AIORateLimiter, filters
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
    cur.execute("""CREATE TABLE IF NOT EXISTS chat_settings(
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
    cur.execute("""CREATE TABLE IF NOT EXISTS whitelist(
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, text TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS blacklist(
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, text TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS pro_keys(
        key TEXT PRIMARY KEY, months INTEGER, created_at TEXT,
        used_by INTEGER NULL, expires_at TEXT NULL
    )""")
    _ensure_col(cur, "trial_used", "INTEGER DEFAULT 0")
    _ensure_col(cur, "last_pro_notice", "TEXT NULL")
    conn.commit(); conn.close()

# ================== HELPERS ==================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def now_utc():
    return datetime.utcnow()

async def safe_reply_private(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """
    Ưu tiên gửi DM; nếu không được thì báo tối thiểu trong nhóm.
    """
    user_id = update.effective_user.id if update and update.effective_user else None
    chat_id = update.effective_chat.id if update and update.effective_chat else None

    try:
        if user_id:
            await context.bot.send_message(chat_id=user_id, text=text, **kwargs)
            return
    except Exception as e:
        logger.warning("safe_reply_private DM fail: %s", e)

    # Fallback group (loại bỏ reply_markup nếu có)
    try:
        if chat_id:
            clean_kwargs = {k: v for k, v in kwargs.items() if k != "reply_markup"}
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"(🔔 Chỉ báo cho admin) {text}\n\nℹ️ Nếu muốn nhận tin riêng, hãy mở DM với bot và gửi /start.",
                **clean_kwargs
            )
    except Exception as e2:
        logger.warning("safe_reply_private group fallback fail: %s", e2)

def get_setting(chat_id: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT nolinks,noforwards,nobots,antiflood,noevents,
                          pro_until,trial_used,last_pro_notice
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

# ----- whitelist/blacklist utils -----
def add_whitelist(chat_id, text):
    conn=_conn(); cur=conn.cursor()
    cur.execute("INSERT INTO whitelist(chat_id,text) VALUES(?,?)", (chat_id, text.strip()))
    conn.commit(); conn.close()

def remove_whitelist(chat_id, text):
    conn=_conn(); cur=conn.cursor()
    cur.execute("DELETE FROM whitelist WHERE chat_id=? AND text=?", (chat_id, text.strip()))
    conn.commit(); conn.close()

def list_whitelist(chat_id):
    conn=_conn(); cur=conn.cursor()
    cur.execute("SELECT text FROM whitelist WHERE chat_id=?", (chat_id,))
    r=[x[0] for x in cur.fetchall()]; conn.close(); return r

def add_blacklist(chat_id, text):
    conn=_conn(); cur=conn.cursor()
    cur.execute("INSERT INTO blacklist(chat_id,text) VALUES(?,?)", (chat_id, text.strip()))
    conn.commit(); conn.close()

def remove_blacklist(chat_id, text):
    conn=_conn(); cur=conn.cursor()
    cur.execute("DELETE FROM blacklist WHERE chat_id=? AND text=?", (chat_id, text.strip()))
    conn.commit(); conn.close()

def list_blacklist(chat_id):
    conn=_conn(); cur=conn.cursor()
    cur.execute("SELECT text FROM blacklist WHERE chat_id=?", (chat_id,))
    r=[x[0] for x in cur.fetchall()]; conn.close(); return r

# ----- Pro keys -----
def gen_key(months=1):
    key = secrets.token_urlsafe(12)
    created = now_utc()
    expires = created + timedelta(days=30*int(months))
    conn=_conn(); cur=_conn().cursor()  # use fresh connection to be safe
    conn=_conn(); cur=conn.cursor()
    cur.execute("INSERT INTO pro_keys(key,months,created_at,expires_at) VALUES(?,?,?,?)",
                (key, months, created.isoformat(), expires.isoformat()))
    conn.commit(); conn.close()
    return key, expires

def list_keys():
    conn=_conn(); cur=conn.cursor()
    cur.execute("SELECT key,months,created_at,expires_at,used_by FROM pro_keys")
    rows=cur.fetchall(); conn.close(); return rows

def consume_key(key: str, user_id: int):
    conn=_conn(); cur=conn.cursor()
    cur.execute("SELECT key,months,created_at,expires_at,used_by FROM pro_keys WHERE key=?", (key,))
    row=cur.fetchone()
    if not row:
        conn.close(); return False, "invalid", None
    if row[4]:
        conn.close(); return False, "used", None
    exp = datetime.fromisoformat(row[3])
    if exp < now_utc():
        conn.close(); return False, "expired", None
    cur.execute("UPDATE pro_keys SET used_by=? WHERE key=?", (user_id, key))
    conn.commit(); conn.close()
    return True, None, int(row[1])

# ================== REGEX / FLOOD ==================
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
    Trả về list[str] (đã loại trùng).
    """
    text = msg.text or msg.caption or ""
    found = []

    entities = []
    if msg.entities:
        entities.extend(msg.entities)
    if msg.caption_entities:
        entities.extend(msg.caption_entities)

    for ent in entities:
        t = getattr(ent, "type", "")
        if t == "text_link" and getattr(ent, "url", None):
            found.append(ent.url)
        elif t in ("url", "email"):
            try:
                start = ent.offset
                end = ent.offset + ent.length
                found.append(text[start:end])
            except Exception:
                pass

    found.extend(DOMAIN_RE.findall(text))
    found.extend(IPV4_RE.findall(text))

    uniq, seen = [], set()
    for u in found:
        u = u.strip()
        if u and u.lower() not in seen:
            uniq.append(u)
            seen.add(u.lower())
    return uniq

FLOOD_WINDOW, FLOOD_LIMIT = 20, 3
user_buckets = {}

def _is_flood(chat_id, user_id):
    k = (chat_id, user_id)
    dq = user_buckets.get(k); now = time.time()
    if dq is None:
        dq = deque(maxlen=FLOOD_LIMIT); user_buckets[k] = dq
    while dq and now - dq[0] > FLOOD_WINDOW:
        dq.popleft()
    dq.append(now)
    return len(dq) > FLOOD_LIMIT

# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_reply_private(
        update, context,
        "🤖 HotroSecurityBot đang hoạt động!\nGõ /help để xem hướng dẫn chi tiết."
    )

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    await safe_reply_private(update, context, f"🆔 Your user_id: `{uid}`", parse_mode=ParseMode.MARKDOWN)

async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id if update.effective_chat else None
    await safe_reply_private(update, context, f"💬 This chat_id: `{cid}`", parse_mode=ParseMode.MARKDOWN)

def _help_text_free():
    return """🛡 *HƯỚNG DẪN SỬ DỤNG CƠ BẢN*

ℹ️ *Lưu ý:* Gõ `/help` trong group chỉ admin mới nhận hướng dẫn chi tiết qua DM.

🚀 *Bắt đầu*
• Thêm bot vào nhóm → cấp quyền xoá tin nhắn.
• Mở DM với bot và gửi `/start` để nhận thông báo riêng (DM).

📌 *Quản lý nhóm*
• `/status` → Xem cấu hình hiện tại, hạn Pro.
• `/nolinks on|off` → Bật/tắt chặn *link & @mention* (dùng whitelist để cho phép).
• `/noforwards on|off` → Chặn tin nhắn *forward*.
• `/nobots on|off` → Cấm mời thêm bot vào nhóm.

📜 *Danh sách*
• `/whitelist_add <text>` / `/whitelist_remove <text>` / `/whitelist_list`
• `/blacklist_add <text>`  / `/blacklist_remove <text>`  / `/blacklist_list`

🧪 *Dùng thử Pro 7 ngày (admin)*
• `/trial7` → Kích hoạt Pro dùng thử cho *nhóm hiện tại* (1 lần/nhóm).

🔑 *Nâng cấp bằng key*
• `/applykey <key>` → Kích hoạt/gia hạn Pro
• `/genkey <tháng>` → (Admin) tạo key nhanh. Ví dụ: `/genkey 1`
""".strip()

def _help_text_pro():
    return """💎 *HOTRO SECURITY PRO – ĐÃ KÍCH HOẠT*

⚙️ *Cài đặt chính*
• `/status` → Xem cấu hình & hạn Pro
• `/nolinks on|off` → Chặn link & @mention (kết hợp whitelist)
• `/noforwards on|off` → Chặn forward
• `/nobots on|off` → Cấm mời bot
• `/noevents on|off` → Ẩn join/leave
• `/antiflood on|off` → Chống spam: xoá khi >3 tin/20s/người

📜 *Danh sách*
• `/whitelist_add <text>` / `/whitelist_remove <text>` / `/whitelist_list`
• `/blacklist_add <text>` / `/blacklist_remove <text>` / `/blacklist_list`

🔑 *Key*
• `/applykey <key>` → Kích hoạt/gia hạn
• `/genkey <tháng>` → (Admin) tạo key
• `/keys_list` → (Admin) xem danh sách key

🧭 *Quy tắc*
• Admin bypass các bộ lọc.
• Blacklist ưu tiên xoá ngay.
• Whitelist cho phép link/mention/từ khoá cụ thể vượt lọc.
""".strip()

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id = update.effective_user.id
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) and not is_admin(user_id):
        return
    pro = is_pro(chat.id)
    text = _help_text_pro() if pro else _help_text_free()
    await safe_reply_private(update, context, text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_setting(update.effective_chat.id)
    wl = list_whitelist(update.effective_chat.id); bl = list_blacklist(update.effective_chat.id)
    pro_txt = f"⏳ Pro đến {s['pro_until'].strftime('%d/%m/%Y %H:%M UTC')}" if s["pro_until"] else "❌ Chưa có Pro"
    txt = (
        "📋 Cấu hình:\n"
        f"nolinks={s['nolinks']} | noforwards={s['noforwards']} | nobots={s['nobots']} "
        f"| antiflood={s['antiflood']} | noevents={s['noevents']}\n"
        f"{pro_txt}\n"
        f"Whitelist: {', '.join(wl) if wl else '(none)'}\n"
        f"Blacklist: {', '.join(bl) if bl else '(none)'}"
    )
    await safe_reply_private(update, context, txt)

async def _toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, pro: bool = False):
    if not is_admin(update.effective_user.id):
        await safe_reply_private(update, context, "❌ Bạn không phải admin."); return
    if pro and not is_pro(update.effective_chat.id):
        await safe_reply_private(update, context, f"🔒 {field} chỉ dành cho Pro."); return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await safe_reply_private(update, context, f"Usage: /{field} on|off"); return
    val = 1 if context.args[0].lower() == "on" else 0
    set_setting(update.effective_chat.id, field, val)
    await safe_reply_private(update, context, f"✅ {field} = {'on' if val else 'off'}")

async def nolinks(update, context):    await _toggle(update, context, "nolinks")
async def noforwards(update, context): await _toggle(update, context, "noforwards")
async def nobots(update, context):     await _toggle(update, context, "nobots")
async def antiflood(update, context):  await _toggle(update, context, "antiflood", pro=True)
async def noevents(update, context):   await _toggle(update, context, "noevents",  pro=True)

# ----- WL/BL Commands -----
async def whitelist_add_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await safe_reply_private(update, context, "❌ Bạn không phải admin."); return
    if not context.args:
        await safe_reply_private(update, context, "Usage: /whitelist_add <text>"); return
    add_whitelist(update.effective_chat.id, " ".join(context.args))
    await safe_reply_private(update, context, "✅ Đã thêm vào whitelist.")

async def whitelist_remove_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await safe_reply_private(update, context, "❌ Bạn không phải admin."); return
    if not context.args:
        await safe_reply_private(update, context, "Usage: /whitelist_remove <text>"); return
    remove_whitelist(update.effective_chat.id, " ".join(context.args))
    await safe_reply_private(update, context, "✅ Đã xoá khỏi whitelist.")

async def whitelist_list_cmd(update, context):
    wl = list_whitelist(update.effective_chat.id)
    await safe_reply_private(update, context, "📄 Whitelist:\n" + ("\n".join(wl) if wl else "(trống)"))

async def blacklist_add_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await safe_reply_private(update, context, "❌ Bạn không phải admin."); return
    if not context.args:
        await safe_reply_private(update, context, "Usage: /blacklist_add <text>"); return
    add_blacklist(update.effective_chat.id, " ".join(context.args))
    await safe_reply_private(update, context, "✅ Đã thêm vào blacklist.")

async def blacklist_remove_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await safe_reply_private(update, context, "❌ Bạn không phải admin."); return
    if not context.args:
        await safe_reply_private(update, context, "Usage: /blacklist_remove <text>"); return
    remove_blacklist(update.effective_chat.id, " ".join(context.args))
    await safe_reply_private(update, context, "✅ Đã xoá khỏi blacklist.")

async def blacklist_list_cmd(update, context):
    bl = list_blacklist(update.effective_chat.id)
    await safe_reply_private(update, context, "📄 Blacklist:\n" + ("\n".join(bl) if bl else "(trống)"))

# ----- Key Commands -----
async def genkey_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await safe_reply_private(update, context, "❌ Bạn không phải admin."); return
    months = 1
    if context.args:
        try:
            months = int(context.args[0])
        except Exception:
            await safe_reply_private(update, context, "Usage: /genkey <tháng>"); return
    k, exp = gen_key(months)
    await safe_reply_private(
        update, context,
        f"🔑 Key: `{k}`\nHiệu lực {months} tháng (tạo đến {exp.strftime('%d/%m/%Y %H:%M UTC')}).",
        parse_mode=ParseMode.MARKDOWN
    )

async def keys_list_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await safe_reply_private(update, context, "❌ Bạn không phải admin."); return
    rows = list_keys()
    if not rows:
        await safe_reply_private(update, context, "(Chưa có key)"); return
    out = ["🗝 Danh sách key:"]
    for k, m, c, e, u in rows:
        out.append(f"{k} | {m} tháng | tạo:{c} | hết hạn:{e} | used_by:{u}")
    await safe_reply_private(update, context, "\n".join(out))

async def applykey_cmd(update, context):
    if not context.args:
        await safe_reply_private(update, context, "Usage: /applykey <key>"); return
    ok, reason, months = consume_key(context.args[0].strip(), update.effective_user.id)
    if not ok:
        m = {"invalid": "❌ Key sai", "used": "❌ Key đã dùng", "expired": "❌ Key hết hạn"}[reason]
        await safe_reply_private(update, context, m); return
    s = get_setting(update.effective_chat.id)
    base = s["pro_until"] if s["pro_until"] and s["pro_until"] > now_utc() else now_utc()
    new = base + timedelta(days=30*months); set_pro_until(update.effective_chat.id, new)
    await safe_reply_private(update, context, f"✅ Pro kích hoạt đến {new.strftime('%d/%m/%Y %H:%M UTC')}")

# ----- Trial 7 days -----
async def trial7_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await safe_reply_private(update, context, "❌ Chỉ admin mới kích hoạt dùng thử."); return

    target_chat_id = update.effective_chat.id

    if update.effective_chat.type == ChatType.PRIVATE and not context.args:
        await safe_reply_private(
            update, context,
            "ℹ️ Bạn đang dùng trong DM.\n• Vào nhóm và gõ /trial7\n"
            "• Hoặc dùng `/trial7 <chat_id>` để bật nhóm cụ thể.\n"
            "Dùng /chatid trong nhóm để lấy chat_id.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if context.args:
        try:
            target_chat_id = int(context.args[0])
        except Exception:
            await safe_reply_private(update, context, "Usage: /trial7 [chat_id]\nVí dụ: /trial7 -1001234567890")
            return

    s = get_setting(target_chat_id)
    if s["trial_used"]:
        await safe_reply_private(update, context, "ℹ️ Nhóm này đã dùng thử trước đó."); return
    if is_pro(target_chat_id):
        await safe_reply_private(update, context, "ℹ️ Nhóm đang ở trạng thái Pro rồi."); return

    until = now_utc() + timedelta(days=7)
    set_pro_until(target_chat_id, until); set_trial_used(target_chat_id, True)
    where_txt = "nhóm hiện tại" if target_chat_id == update.effective_chat.id else f"chat_id {target_chat_id}"
    await safe_reply_private(
        update, context,
        f"🎁 Đã kích hoạt *Pro dùng thử 7 ngày* cho {where_txt} đến {until.strftime('%d/%m/%Y %H:%M UTC')}.",
        parse_mode=ParseMode.MARKDOWN
    )

# ----- Scheduler: check pro expiry -----
async def pro_expiry_check(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn=_conn(); cur=conn.cursor()
        cur.execute("SELECT chat_id, pro_until, last_pro_notice FROM chat_settings")
        rows = cur.fetchall(); conn.close()
        for chat_id, pro_until, last_notice in rows:
            if not pro_until:
                continue
            pro_dt = datetime.fromisoformat(pro_until)
            if pro_dt > now_utc():
                if last_notice:
                    set_last_pro_notice(chat_id, None)
                continue
            if not last_notice:
                set_pro_until(chat_id, now_utc() - timedelta(seconds=1))
                set_last_pro_notice(chat_id, now_utc())
                msg = ("⛔ Gói Pro của nhóm đã *hết hạn dùng thử/keys*.\n"
                       "Vui lòng liên hệ admin để gia hạn hoặc dùng /applykey <key>.")
                try:
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logger.warning("Notify expiry failed for %s: %s", chat_id, e)
    except Exception as e:
        logger.error("pro_expiry_check error: %s", e)

# ================== MESSAGE HANDLER ==================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    s = get_setting(chat_id)
    wl = list_whitelist(chat_id)
    bl = list_blacklist(chat_id)
    txt = msg.text or msg.caption or ""

    # Admin bypass
    if is_admin(user_id):
        return

    # Blacklist ưu tiên
    if any(b.lower() in txt.lower() for b in bl):
        try:
            await msg.delete()
        except Exception:
            pass
        return

    # Link & mentions
    mentions = MENTION_RE.findall(txt)
    urls = extract_links(msg)

    if s["nolinks"]:
        if urls:
            allowed = False
            if wl:
                for u in urls:
                    if any(w.lower() in u.lower() for w in wl):
                        allowed = True; break
            if not allowed:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        if mentions:
            for m in mentions:
                if not any(w.lower() in m.lower() for w in wl):
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return

    # Forwards
    if s["noforwards"] and (msg.forward_date or getattr(msg, "forward_from", None) or getattr(msg, "forward_from_chat", None)):
        try:
            await msg.delete()
        except Exception:
            pass
        return

    # Anti-flood (Pro)
    if s["antiflood"]:
        if not is_pro(chat_id):
            return
        if _is_flood(chat_id, user_id):
            try:
                await msg.delete()
            except Exception:
                pass
            return

# ================== BOOT (PTB20 + Flask) ==================
def start_bot():
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing"); return

    application: Application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .rate_limiter(AIORateLimiter())
        .build()
    )

    # Post-init: clear webhook & start scheduler
    def on_post_init(app: Application):
        try:
            # chạy async trong loop của app
            app.create_task(app.bot.delete_webhook(drop_pending_updates=True))
            logger.info("Webhook cleared successfully before polling.")
        except Exception as e:
            logger.warning(f"Failed to delete webhook: {e}")
        app.job_queue.run_repeating(pro_expiry_check, interval=30*60, first=60)

    application.post_init = on_post_init

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("myid", myid_cmd))
    application.add_handler(CommandHandler("chatid", chatid_cmd))

    application.add_handler(CommandHandler("nolinks", nolinks))
    application.add_handler(CommandHandler("noforwards", noforwards))
    application.add_handler(CommandHandler("nobots", nobots))
    application.add_handler(CommandHandler("antiflood", antiflood))
    application.add_handler(CommandHandler("noevents", noevents))

    application.add_handler(CommandHandler("whitelist_add", whitelist_add_cmd))
    application.add_handler(CommandHandler("whitelist_remove", whitelist_remove_cmd))
    application.add_handler(CommandHandler("whitelist_list", whitelist_list_cmd))
    application.add_handler(CommandHandler("blacklist_add", blacklist_add_cmd))
    application.add_handler(CommandHandler("blacklist_remove", blacklist_remove_cmd))
    application.add_handler(CommandHandler("blacklist_list", blacklist_list_cmd))

    application.add_handler(CommandHandler("genkey", genkey_cmd))
    application.add_handler(CommandHandler("keys_list", keys_list_cmd))
    application.add_handler(CommandHandler("applykey", applykey_cmd))
    application.add_handler(CommandHandler("trial7", trial7_cmd))

    # Messages (bắt text/caption/service đều được)
    application.add_handler(MessageHandler(filters.ALL, message_handler))

    # Run polling in a background thread (để Flask sống cùng)
    threading.Thread(
        target=lambda: application.run_polling(
            close_loop=False,
            allowed_updates=Update.ALL_TYPES
        ),
        daemon=True
    ).start()

# Flask keep-alive (Render)
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ HotroSecurityBot running (PTB20) – OK"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    t = threading.Thread(target=start_bot, daemon=True); t.start()
    run_flask()
