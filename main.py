import sys
sys.modules.pop("core.models", None)  # tránh import vòng khi redeploy

import os, re
from datetime import datetime, timezone, timedelta

from telegram import (
    Update, ChatPermissions,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.constants import ParseMode
    # Conflict dùng cho on_error
from telegram.error import Conflict
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)

# ====== LOCAL MODELS ======
from core.models import (
    init_db, SessionLocal, Setting, Filter, Whitelist,
    User, count_users, Warning, Blacklist
)
from core.models import (
    init_db, SessionLocal, Setting, Filter, Whitelist,
    User, count_users, Warning, Blacklist,
    Supporter, SupportSetting, list_supporters, get_support_enabled   # <-- thêm
)

# ====== I18N ======
from core.lang import t, LANG  # dùng bộ ngôn ngữ

# ====== KEEP ALIVE WEB ======
# (các import ở trên)
from keep_alive_server import keep_alive

# === Helper lấy user từ reply hoặc từ tham số ===
def _get_target_user(update: Update, args) -> tuple[int | None, str]:
    """
    Trả về (user_id, display_name) từ reply hoặc từ args[0] (user_id).
    """
    msg = update.effective_message
    if msg.reply_to_message:
        u = msg.reply_to_message.from_user
        name = u.full_name or (u.username and f"@{u.username}") or str(u.id)
        return u.id, name

    if args:
        try:
            uid = int(args[0])
            return uid, str(uid)
        except Exception:
            return None, ""
    return None, ""

# ====== ENV ======
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME", "").strip()

# ====== STATE / REGEX ======
FLOOD = {}
LINK_RE = re.compile(
    r"(https?://|www\.|t\.me/|@\w+|[a-zA-Z0-9-]+\.(com|net|org|vn|xyz|info|io|co)(/[^\s]*)?)",
    re.IGNORECASE
)
def remove_links(text: str) -> str:
    """Thay mọi link bằng [link bị xóa] nhưng giữ lại chữ mô tả."""
    return re.sub(LINK_RE, "[link bị xóa]", text or "")

# ====== TZ-SAFE HELPERS ======
def utcnow():
    return datetime.now(timezone.utc)

def to_host(domain_or_url: str) -> str:
    """Chuẩn hoá đầu vào thành host (không schema, không path), lowercase."""
    s = (domain_or_url or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0].split("?")[0].strip()
    if s.startswith("www."):
        s = s[4:]
    return s
# --- helpers cho whitelist/link ---
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
DOMAIN_RE = re.compile(r"\b([a-z0-9][a-z0-9\-\.]+\.[a-z]{2,})\b", re.IGNORECASE)

def extract_hosts(text: str) -> list[str]:
    text = text or ""
    hosts = []
    for m in URL_RE.findall(text):
        hosts.append(to_host(m))
    for m in DOMAIN_RE.findall(text):
        hosts.append(to_host(m))
    out, seen = [], set()
    for h in hosts:
        if h and h not in seen:
            out.append(h); seen.add(h)
    return out

def host_allowed(host: str, allow_list: list[str]) -> bool:
    host = to_host(host)
    for d in allow_list:
        d = to_host(d)
        if not d:
            continue
        if host == d or host.endswith("." + d):
            return True
    return False

# ====== PRO modules (an toàn nếu thiếu) ======
try:
    from pro.handlers import register_handlers  # (PRO: không đăng ký wl_add tại đây)
except Exception as e:
    print("pro.handlers warn:", e)
    register_handlers = lambda app, **kw: None

try:
    from pro.scheduler import attach_scheduler
except Exception as e:
    print("pro.scheduler warn:", e)
    attach_scheduler = lambda app: None

# ====== UPTIME UTILS ======
START_AT = datetime.now(timezone.utc)

def _fmt_td(td: timedelta) -> str:
    s = int(td.total_seconds())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

# ====== Helpers ======
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

# ====== ADMIN / GROUP CHECKS ======
async def _must_admin_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("⚠️ Lệnh này chỉ dùng trong nhóm.")
        return False
    try:
        m = await context.bot.get_chat_member(chat.id, update.effective_user.id)
        if m.status not in ("administrator", "creator"):
            await update.effective_message.reply_text("⚠️ Chỉ admin mới dùng lệnh này.")
            return False
        return True
    except Exception:
        await update.effective_message.reply_text("⚠️ Không thể kiểm tra quyền admin.")
        return False

# ====== Chọn ngôn ngữ (lưu tạm theo user) ======
USER_LANG = {}  # {user_id: "vi"|"en"}

async def on_lang_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý các nút Languages / chọn ngôn ngữ."""
    q = update.callback_query
    await q.answer()
    data = (q.data or "").strip()

    if data == "lang_menu":
        kb = [[
            InlineKeyboardButton("🇻🇳 Tiếng Việt", callback_data="lang_vi"),
            InlineKeyboardButton("🇬🇧 English",    callback_data="lang_en"),
        ]]
        return await q.edit_message_reply_markup(InlineKeyboardMarkup(kb))

    if data == "lang_vi":
        USER_LANG[q.from_user.id] = "vi"
        await q.edit_message_reply_markup(reply_markup=None)
        return await q.message.reply_text(LANG["vi"]["lang_switched"])

    if data == "lang_en":
        USER_LANG[q.from_user.id] = "en"
        await q.edit_message_reply_markup(reply_markup=None)
        return await q.message.reply_text(LANG["en"]["lang_switched"])

# ====== Commands ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    user = update.effective_user
    db = SessionLocal()
    u = db.get(User, user.id)
    if not u:
        u = User(id=user.id, username=user.username or "")
        db.add(u)
        db.commit()
    total = count_users()
    db.close()

    lang = USER_LANG.get(user.id, "vi")
    hello = t(lang, "start", name=user.first_name, count=total)

    msg = (
        "🤖 <b>HotroSecurityBot</b>\n\n"
        f"{hello}\n\n"
        f"{'Gõ /help để xem danh sách lệnh 💬' if lang=='vi' else 'Type /help to see all commands 💬'}"
    )

    keyboard = [[InlineKeyboardButton("Languages", callback_data="lang_menu")]]
    await m.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = USER_LANG.get(update.effective_user.id, "vi")
    await update.effective_message.reply_text(
        LANG[lang]["help_full"], parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )

async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang_now = USER_LANG.get(update.effective_user.id, "vi")
    if not context.args:
        return await m.reply_text(LANG[lang_now]["lang_usage"])
    code = context.args[0].lower()
    if code not in ("vi", "en"):
        return await m.reply_text(LANG[lang_now]["lang_usage"])
    USER_LANG[update.effective_user.id] = code
    await m.reply_text(LANG[code]["lang_switched"])

# ====== STATS / STATUS / UPTIME / PING ======
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = count_users()
    await update.effective_message.reply_text(f"📊 Tổng người dùng bot: {total:,}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t0 = datetime.now(timezone.utc)
    m = update.effective_message
    msg = await m.reply_text("⏳ Đang đo ping…")
    dt = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    up = datetime.now(timezone.utc) - START_AT
    await msg.edit_text(f"✅ Online | 🕒 Uptime: {_fmt_td(up)} | 🏓 Ping: {dt:.0f} ms")

async def uptime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    up = datetime.now(timezone.utc) - START_AT
    await update.effective_message.reply_text(f"⏱ Uptime: {_fmt_td(up)}")

async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t0 = datetime.now(timezone.utc)
    m = await update.effective_message.reply_text("Pinging…")
    dt = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    await m.edit_text(f"🏓 Pong: {dt:.0f} ms")

# ====== PRO: Admin reply → /warn ======
async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id# ====== PRO: Admin reply → /warn ======
async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    admin_user = update.effective_user

    if not msg.reply_to_message:
        return await msg.reply_text("Hãy reply vào tin có link rồi gõ /warn")

    try:
        member = await context.bot.get_chat_member(chat_id, admin_user.id)
        if member.status not in ("administrator", "creator"):
            return await msg.reply_text("Chỉ admin mới dùng lệnh này.")
    except Exception:
        return await msg.reply_text("Không thể kiểm tra quyền admin.")

    target_msg = msg.reply_to_message
    target_user = target_msg.from_user
    text = (target_msg.text or target_msg.caption or "")

    if not LINK_RE.search(text):
        return await msg.reply_text("Tin được reply không chứa link.")

    db = SessionLocal()

    # ---- Kiểm tra whitelist (nằm TRONG hàm) ----
    wl_hosts = [w.domain for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
    msg_hosts = extract_hosts(text)
    if any(host_allowed(h, wl_hosts) for h in msg_hosts):
        db.close()
        return await msg.reply_text("Domain này nằm trong whitelist, không cảnh báo.")
    # --------------------------------------------

    # Xóa tin vi phạm + thông báo đã xóa link (ẩn link)
    try:
        await target_msg.delete()
    except Exception:
        pass

    safe_text = remove_links(text)
    try:
        await context.bot.send_message(chat_id, f"🔒 Tin đã xóa link: {safe_text}")
    except Exception:
        pass

    # Tăng cảnh cáo
    w = db.query(Warning).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
    if not w:
        w = Warning(chat_id=chat_id, user_id=target_user.id, count=1)
        db.add(w)
    else:
        w.count += 1
        w.last_warned = utcnow()
    db.commit()

    await context.bot.send_message(
        chat_id,
        f"⚠️ <b>Cảnh báo:</b> <a href='tg://user?id={target_user.id}'>Người này</a> đã chia sẻ link không được phép. ({w.count}/3)",
        parse_mode=ParseMode.HTML
    )

    # --- AUTO BAN theo số lần cảnh cáo ---
    try:
        if 3 <= w.count < 5:
            # mute 24h
            until = datetime.now(timezone.utc) + timedelta(hours=24)
            await context.bot.restrict_chat_member(
                chat_id,
                target_user.id,
                ChatPermissions(can_send_messages=False),
                until_date=until
            )
            await context.bot.send_message(
                chat_id,
                "🚫 Người này bị cấm 24h do vi phạm nhiều lần (>=3).",
                parse_mode=ParseMode.HTML
            )

        elif w.count >= 5:
            # Ban hẳn + thêm vào blacklist
            await context.bot.ban_chat_member(chat_id, target_user.id)
            await context.bot.send_message(
                chat_id,
                "⛔️ Người này đã bị kick khỏi nhóm do tái phạm quá nhiều lần (>=5).",
                parse_mode=ParseMode.HTML
            )

            bl = db.query(Blacklist).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
            if not bl:
                db.add(Blacklist(chat_id=chat_id, user_id=target_user.id))
                db.commit()

            # Thông báo đưa vào blacklist
            await context.bot.send_message(
                chat_id,
                f"🚫 <b>Đã đưa vào danh sách đen:</b> <a href='tg://user?id={target_user.id}'>Người này</a>.",
                parse_mode=ParseMode.HTML
            )
    except Exception:
        pass

    db.close()


# ====== WARN INFO / CLEAR / TOP ======
async def warn_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem số lần cảnh cáo của 1 thành viên (reply hoặc /warn_info <user_id>)."""
    chat_id = update.effective_chat.id
    uid, name = _get_target_user(update, context.args)
    if not uid:
        await update.effective_message.reply_text(
            "Reply tin nhắn hoặc dùng: /warn_info <user_id>"
        )
        return

    db = SessionLocal()
    try:
        row = db.query(Warning).filter_by(chat_id=chat_id, user_id=uid).one_or_none()
        count = row.count if row else 0
        await update.effective_message.reply_text(f"⚠️ {name} hiện có {count} cảnh cáo.")
    finally:
        db.close()


async def warn_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xoá toàn bộ cảnh cáo của 1 thành viên (chỉ admin)."""
    if not await _must_admin_in_group(update, context):
        return

    chat_id = update.effective_chat.id
    uid, name = _get_target_user(update, context.args)
    if not uid:
        await update.effective_message.reply_text(
            "Reply tin nhắn hoặc dùng: /warn_clear <user_id>"
        )
        return

    db = SessionLocal()
    try:
        row = db.query(Warning).filter_by(chat_id=chat_id, user_id=uid).one_or_none()
        if row:
            row.count = 0
            db.commit()
            await update.effective_message.reply_text(f"✅ Đã xoá toàn bộ cảnh cáo của {name}.")
        else:
            await update.effective_message.reply_text("Người này chưa có cảnh cáo nào.")
    finally:
        db.close()


async def warn_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Top 10 thành viên bị cảnh cáo nhiều nhất trong nhóm."""
    chat_id = update.effective_chat.id
    db = SessionLocal()
    try:
        rows = (
            db.query(Warning)
              .filter_by(chat_id=chat_id)
              .order_by(Warning.count.desc())
              .limit(10)
              .all()
        )
        if not rows:
            await update.effective_message.reply_text("Chưa có ai bị cảnh cáo.")
            return

        lines, rank = [], 1
        for r in rows:
            lines.append(f"{rank}. user_id {r.user_id}: {r.count} cảnh cáo")
            rank += 1

        await update.effective_message.reply_text("🏆 Top cảnh cáo:\n" + "\n".join(lines))
    finally:
        db.close()

# ====== Entrypoint ======
if __name__ == "__main__":
    main()
