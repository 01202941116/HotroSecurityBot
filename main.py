# HotroSecurityBot - Full (Render + PTB 13.15) + Pro LOCKED UI + Pro Auto Ads
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
    conn.commit()
    # ensure columns (for upgrades)
    def ensure_col(col, type_sql):
        cur.execute("PRAGMA table_info(chat_settings)")
        cols = [r[1] for r in cur.fetchall()]
        if col not in cols:
            cur.execute(f"ALTER TABLE chat_settings ADD COLUMN {col} {type_sql}")
            conn.commit()
    ensure_col("noevents", "INTEGER DEFAULT 0")
    ensure_col("pro_until", "TEXT NULL")
    conn.close()

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

def require_pro(update: Update, feature_name: str) -> bool:
    """Trả False nếu chưa kích hoạt Pro (và gửi gợi ý)."""
    chat_id = update.effective_chat.id
    if is_pro(chat_id):
        return True
    update.message.reply_text(
        f"🔒 Tính năng *{feature_name}* chỉ dành cho gói *Pro*.\n"
        f"Vui lòng dùng `/applykey <key>` để kích hoạt Pro cho nhóm.",
        parse_mode=ParseMode.MARKDOWN
    )
    return False

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
    cur.execute("INSERT INTO whitelist(chat_id, text) VALUES(?,?)", (chat_id, text))
    conn.commit(); conn.close()

def remove_whitelist(chat_id, text):
    conn = _conn(); cur = conn.cursor()
    cur.execute("DELETE FROM whitelist WHERE chat_id=? AND text=?", (chat_id, text))
    conn.commit(); conn.close()

def list_whitelist(chat_id):
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT text FROM whitelist WHERE chat_id=?", (chat_id,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close(); return rows

def add_blacklist(chat_id, text):
    conn = _conn(); cur = conn.cursor()
    cur.execute("INSERT INTO blacklist(chat_id, text) VALUES(?,?)", (chat_id, text))
    conn.commit(); conn.close()

def remove_blacklist(chat_id, text):
    conn = _conn(); cur = conn.cursor()
    cur.execute("DELETE FROM blacklist WHERE chat_id=? AND text=?", (chat_id, text))
    conn.commit(); conn.close()

def list_blacklist(chat_id):
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT text FROM blacklist WHERE chat_id=?", (chat_id,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close(); return rows

# Pro keys
def gen_key(months=1):
    key = secrets.token_urlsafe(12)
    created = now_utc()
    expires = created + timedelta(days=30 * int(months))
    conn = _conn(); cur = conn.cursor()
    cur.execute("INSERT INTO pro_keys(key, months, created_at, expires_at) VALUES(?,?,?,?)",
                (key, months, created.isoformat(), expires.isoformat()))
    conn.commit(); conn.close()
    return key, expires

def list_keys():
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT key, months, created_at, expires_at, used_by FROM pro_keys")
    rows = cur.fetchall(); conn.close()
    return rows

def consume_key(key: str, user_id: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT key, months, created_at, expires_at, used_by FROM pro_keys WHERE key=?", (key,))
    row = cur.fetchone()
    if not row:
        conn.close(); return False, "invalid", None
    if row[4] is not None:
        conn.close(); return False, "used", None
    exp = datetime.fromisoformat(row[3])
    if exp < now_utc():
        conn.close(); return False, "expired", None
    cur.execute("UPDATE pro_keys SET used_by=? WHERE key=?", (user_id, key))
    conn.commit(); conn.close()
    return True, None, int(row[1])

# ================== FILTERS / STATE ==================
URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
MENTION_RE = re.compile(r"@([A-Za-z0-9_]{5,64})")

FLOOD_WINDOW = 20
FLOOD_LIMIT = 3
user_buckets = {}  # {(chat_id, user_id): deque[timestamps]}

def _is_flood(chat_id, user_id):
    key = (chat_id, user_id)
    dq = user_buckets.get(key)
    now = time.time()
    if dq is None:
        dq = deque(maxlen=FLOOD_LIMIT); user_buckets[key] = dq
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

def _pro_keyboard_locked():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Kích hoạt Pro", callback_data="pro_locked:apply")],
        [InlineKeyboardButton("ℹ️ Tính năng gói Pro", callback_data="pro_locked:info")],
    ])

def help_cmd(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    pro_on = is_pro(chat_id)

    core = [
        "🛟 *HƯỚNG DẪN SỬ DỤNG*",
        "",
        "• `/start` – Kiểm tra bot",
        "• `/status` – Xem cấu hình & thời hạn Pro",
        "",
        "*Bật/Tắt (admin)*",
        "• `/nolinks on|off` – Bật/tắt chặn link & @mention",
        "• `/noforwards on|off` – Chặn tin nhắn forward",
        "• `/nobots on|off` – Chặn thành viên mời bot vào",
        "• `/antiflood on|off` – Chống spam (3 tin/20s) " + ("(Pro)" if not pro_on else ""),
        "• `/noevents on|off` – Ẩn thông báo join/left " + ("(Pro)" if not pro_on else ""),
        "",
        "*Whitelist/Blacklist (admin)*",
        "• `/whitelist_add <từ|domain>` / `/whitelist_remove <...>`",
        "• `/whitelist_list` – Liệt kê whitelist",
        "• `/blacklist_add <từ|domain>` / `/blacklist_remove <...>`",
        "• `/blacklist_list` – Liệt kê blacklist",
        "",
    ]

    if pro_on:
        pro_lines = [
            "✨ *Pro (đã kích hoạt)*",
            "• `/applykey <key>` – Gia hạn/áp thêm thời gian",
            "• Tự động quảng cáo định kỳ: `/ads_add`, `/ads_list`, `/ads_pause`, `/ads_resume`, `/ads_delete`",
            "• Siết chặt mentions (xóa mọi @username không nằm trong whitelist)",
            "• Ưu tiên blacklist (xoá ngay lập tức)",
            "• Ẩn sự kiện nâng cao",
        ]
        update.message.reply_text("\n".join(core + pro_lines), parse_mode=ParseMode.MARKDOWN)
    else:
        pro_lines = [
            "🔒 *Pro (chưa kích hoạt)*",
            "• (LOCKED) `/applykey <key>` – Kích hoạt Pro cho *nhóm hiện tại*",
            "• (LOCKED) Tự động quảng cáo định kỳ",
            "• (LOCKED) Siết chặt mentions",
            "• (LOCKED) Ưu tiên blacklist",
            "• (LOCKED) Ẩn sự kiện nâng cao",
        ]
        update.message.reply_text(
            "\n".join(core + pro_lines), parse_mode=ParseMode.MARKDOWN, reply_markup=_pro_keyboard_locked()
        )

def pro_locked_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    _, action = q.data.split(":", 1)
    if action == "apply":
        q.answer("Dùng /applykey <key> để kích hoạt Pro cho nhóm hiện tại.", show_alert=True)
    else:
        q.answer("Pro gồm: siết @mention, ưu tiên blacklist, tự động quảng cáo, ẩn sự kiện nâng cao…", show_alert=True)

def status(update: Update, context: CallbackContext):
    chat = update.effective_chat
    s = get_setting(chat.id)
    wl = list_whitelist(chat.id)
    bl = list_blacklist(chat.id)
    pro_txt = f"⏳ Pro đến {s['pro_until'].strftime('%d/%m/%Y %H:%M UTC')}" if s["pro_until"] else "❌ Chưa kích hoạt Pro"
    text = (f"📋 Cấu hình nhóm {chat.title or chat.id}:\n"
            f"- nolinks={s['nolinks']} | noforwards={s['noforwards']} | "
            f"nobots={s['nobots']} | antiflood={s['antiflood']} | noevents={s['noevents']}\n"
            f"- {pro_txt}\n"
            f"- Whitelist: {', '.join(wl) if wl else '(none)'}\n"
            f"- Blacklist: {', '.join(bl) if bl else '(none)'}")
    update.message.reply_text(text)

# toggles (một số là Pro)
def _toggle(update: Update, context: CallbackContext, field: str, pro_only: bool = False):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if pro_only and not require_pro(update, field):
        return
    if not context.args or context.args[0].lower() not in ("on","off"):
        update.message.reply_text(f"Usage: /{field} on|off"); return
    val = 1 if context.args[0].lower()=="on" else 0
    set_setting(update.effective_chat.id, field, val)
    update.message.reply_text(f"✅ {field} = {'on' if val else 'off'}")

def nolinks(update, context):    _toggle(update, context, "nolinks", pro_only=False)
def noforwards(update, context): _toggle(update, context, "noforwards", pro_only=False)
def nobots(update, context):     _toggle(update, context, "nobots", pro_only=False)
def antiflood(update, context):  _toggle(update, context, "antiflood", pro_only=True)  # Pro
def noevents(update, context):   _toggle(update, context, "noevents", pro_only=True)   # Pro

# whitelist / blacklist
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

# keys
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
        update.message.reply_text("Usage: /applykey <key>\n(Key sẽ kích hoạt Pro cho *nhóm hiện tại*)",
                                  parse_mode=ParseMode.MARKDOWN); return
    ok, reason, months = consume_key(context.args[0].strip(), user.id)
    if not ok:
        update.message.reply_text({
            "invalid":"❌ Key không hợp lệ",
            "used":"❌ Key đã được sử dụng",
            "expired":"❌ Key đã hết hạn"
        }.get(reason, "❌ Không thể dùng key")); return
    s = get_setting(chat.id)
    base = s["pro_until"] if s["pro_until"] and s["pro_until"] > now_utc() else now_utc()
    new_until = base + timedelta(days=30*months)
    set_pro_until(chat.id, new_until)
    update.message.reply_text(f"✅ Đã kích hoạt Pro đến: {new_until.strftime('%d/%m/%Y %H:%M UTC')}")

# ================== ADS (Pro Feature - Auto Ads Scheduler) ==================
def init_ads_table():
    conn = _conn(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS ad_campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        text TEXT,
        interval_min INTEGER,
        next_run TEXT,
        enabled INTEGER DEFAULT 1,
        created_by INTEGER,
        created_at TEXT
    )""")
    conn.commit(); conn.close()

def ads_add(chat_id: int, text: str, interval_min: int, start_time: datetime, created_by: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO ad_campaigns(chat_id, text, interval_min, next_run, enabled, created_by, created_at)
                   VALUES(?,?,?,?,1,?,?)""",
                (chat_id, text, interval_min, start_time.isoformat(), created_by, now_utc().isoformat()))
    conn.commit(); conn.close()

def ads_list(chat_id: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT id, interval_min, next_run, enabled, substr(text,1,80)
                   FROM ad_campaigns WHERE chat_id=? ORDER BY id""", (chat_id,))
    rows = cur.fetchall(); conn.close(); return rows

def ads_toggle(chat_id: int, ad_id: int, on: bool):
    conn = _conn(); cur = conn.cursor()
    cur.execute("UPDATE ad_campaigns SET enabled=? WHERE chat_id=? AND id=?", (1 if on else 0, chat_id, ad_id))
    conn.commit(); conn.close()

def ads_delete(chat_id: int, ad_id: int):
    conn = _conn(); cur = conn.cursor()
    cur.execute("DELETE FROM ad_campaigns WHERE chat_id=? AND id=?", (chat_id, ad_id))
    conn.commit(); conn.close()

def ads_due(now: datetime):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT id, chat_id, text, interval_min, next_run
                   FROM ad_campaigns WHERE enabled=1 AND next_run<=?""", (now.isoformat(),))
    rows = cur.fetchall(); conn.close(); return rows

def ads_bump_next(ad_id: int, minutes: int, last_next_run: str):
    base = datetime.fromisoformat(last_next_run)
    new_next = base + timedelta(minutes=minutes)
    conn = _conn(); cur = conn.cursor()
    cur.execute("UPDATE ad_campaigns SET next_run=? WHERE id=?", (new_next.isoformat(), ad_id))
    conn.commit(); conn.close()

def ads_add_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not require_pro(update, "ads_add"): return
    if len(context.args) < 2:
        update.message.reply_text("Usage: /ads_add <phut> <noi_dung>"); return
    try:
        minutes = int(context.args[0])
        if minutes < 5:
            update.message.reply_text("Khoảng lặp tối thiểu là 5 phút."); return
    except Exception:
        update.message.reply_text("Số phút không hợp lệ."); return
    text = " ".join(context.args[1:]).strip()
    if not text:
        update.message.reply_text("Nội dung quảng cáo trống."); return
    ads_add(update.effective_chat.id, text, minutes, now_utc(), update.effective_user.id)
    update.message.reply_text(f"✅ Đã tạo quảng cáo tự động, lặp mỗi {minutes} phút.")

def ads_list_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    rows = ads_list(update.effective_chat.id)
    if not rows:
        update.message.reply_text("Chưa có quảng cáo nào."); return
    lines = ["📣 Danh sách quảng cáo:"]
    for r in rows:
        _id, interval_min, next_run, enabled, preview = r
        lines.append(f"ID { _id } | {'ON' if enabled else 'OFF'} | mỗi {interval_min}p | {next_run} | \"{preview}\"")
    update.message.reply_text("\n".join(lines))

def ads_pause_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not require_pro(update, "ads_pause"): return
    if not context.args:
        update.message.reply_text("Usage: /ads_pause <id>"); return
    try:
        ad_id = int(context.args[0]); ads_toggle(update.effective_chat.id, ad_id, False)
        update.message.reply_text(f"⏸️ Đã tạm dừng quảng cáo ID {ad_id}.")
    except Exception:
        update.message.reply_text("ID không hợp lệ.")

def ads_resume_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not require_pro(update, "ads_resume"): return
    if not context.args:
        update.message.reply_text("Usage: /ads_resume <id>"); return
    try:
        ad_id = int(context.args[0]); ads_toggle(update.effective_chat.id, ad_id, True)
        update.message.reply_text(f"▶️ Đã bật lại quảng cáo ID {ad_id}.")
    except Exception:
        update.message.reply_text("ID không hợp lệ.")

def ads_delete_cmd(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ Bạn không phải admin."); return
    if not context.args:
        update.message.reply_text("Usage: /ads_delete <id>"); return
    try:
        ad_id = int(context.args[0]); ads_delete(update.effective_chat.id, ad_id)
        update.message.reply_text(f"🗑️ Đã xoá quảng cáo ID {ad_id}.")
    except Exception:
        update.message.reply_text("ID không hợp lệ.")

def ads_worker(bot):
    while True:
        try:
            now = now_utc()
            rows = ads_due(now)
            for (ad_id, chat_id, text, interval_min, next_run) in rows:
                if is_pro(chat_id):
                    try:
                        bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
                    except Exception as e:
                        logger.warning("Gửi QC lỗi %s: %s", chat_id, e)
                ads_bump_next(ad_id, interval_min, next_run)
        except Exception as e:
            logger.error("ads_worker error: %s", e)
        time.sleep(30)

# ================== EVENTS & MODERATION ==================
def delete_service_messages(update: Update, context: CallbackContext):
    if get_setting(update.effective_chat.id)["noevents"]:
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
                try: context.bot.kick_chat_member(update.effective_chat.id, m.id)
                except Exception as e: logger.warning("kick bot fail: %s", e)

def message_handler(update: Update, context: CallbackContext):
    msg = update.message
    if not msg: return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    s = get_setting(chat_id)

    # Anti-flood [Pro]
    if s["antiflood"] and not is_admin(user_id):
        if not is_pro(chat_id) and not require_pro(update, "antiflood"):
            return
        if _is_flood(chat_id, user_id):
            try: msg.delete()
            except Exception: pass
            return

    # Block forwards (Free)
    if s["noforwards"] and (msg.forward_date or msg.forward_from or msg.forward_from_chat):
        try: msg.delete()
        except Exception: pass
        return

    text = msg.text or msg.caption or ""
    wl = list_whitelist(chat_id)
    bl = list_blacklist(chat_id)

    # Blacklist (ưu tiên)
    if any(b.lower() in text.lower() for b in bl):
        try: msg.delete()
        except Exception: pass
        return

    urls = URL_RE.findall(text)
    mentions = MENTION_RE.findall(text)

    # Link filter (Free)
    if s["nolinks"] and urls:
        allowed = any(any(w.lower() in u.lower() for w in wl) for u in urls)
        if not allowed:
            try: msg.delete()
            except Exception: pass
            return

    # Mention filter (siết chặt hơn nếu Pro cũng đã bao phủ ở whitelist)
    if s["nolinks"] and mentions:
        for m in mentions:
            ok = any(w.lower() in m.lower() for w in wl)
            if not ok:
                try: msg.delete()
                except Exception: pass
                return

def error_handler(update, context):
    logger.exception("Exception: %s", context.error)

# ================== START BOT ==================
def start_bot():
    init_db()
    init_ads_table()  # bảng ads
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

    # Pro Ads
    dp.add_handler(CommandHandler("ads_add", ads_add_cmd, pass_args=True))
    dp.add_handler(CommandHandler("ads_list", ads_list_cmd))
    dp.add_handler(CommandHandler("ads_pause", ads_pause_cmd, pass_args=True))
    dp.add_handler(CommandHandler("ads_resume", ads_resume_cmd, pass_args=True))
    dp.add_handler(CommandHandler("ads_delete", ads_delete_cmd, pass_args=True))

    # pro-locked callbacks
    dp.add_handler(CallbackQueryHandler(pro_locked_cb, pattern=r"^pro_locked:"))

    # events
    dp.add_handler(MessageHandler(Filters.status_update, delete_service_messages))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_members))

    # messages
    dp.add_handler(MessageHandler(Filters.text | Filters.entity("url") | Filters.caption, message_handler))

    dp.add_error_handler(error_handler)
    logger.info("🚀 Starting polling...")
    updater.start_polling()

    # chạy worker ads ở background
    threading.Thread(target=ads_worker, args=(updater.bot,), daemon=True).start()

    updater.idle()

# ================== FLASK (Render Free keep-alive) ==================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ HotroSecurityBot is running (Render Free)."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# ================== RUN (Flask main thread; bot background) ==================
if __name__ == "__main__":
    t = threading.Thread(target=start_bot, daemon=True)
    t.start()
    run_flask()
