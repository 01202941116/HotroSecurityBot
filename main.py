import sys
sys.modules.pop("core.models", None)  # tránh import vòng khi redeploy

import os, re, asyncio
from datetime import datetime, timezone, timedelta
from core.models import Warning, Blacklist, get_or_create_autoban, log_violation
from telegram import ChatPermissions
from datetime import datetime, timedelta, timezone
from telegram.constants import ParseMode
from telegram import (
    Update, ChatPermissions,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.constants import ParseMode
    # Conflict dùng để bỏ qua va chạm instance polling
from telegram.error import Conflict
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)

from core.models import set_welcome_message, get_welcome_message

# ====== CHO PHÉP NHỮNG LỆNH NÀO ======
ALLOWED_COMMANDS = {
    "/start", "/help", "/lang", "/stats", "/status", "/uptime", "/ping",
    "/wl_add", "/wl_list", "/wl_del",
    "/filter_add", "/filter_list", "/filter_del",
    "/antilink_on", "/antilink_off",
    "/antimention_on", "/antimention_off",
    "/antiforward_on", "/antiforward_off",
    "/nobots_on", "/nobots_off",
    "/setflood",
    "/warn", "/warn_info", "/warn_clear", "/warn_top",
    "/trial", "/redeem", "/genkey",
    "/support_on", "/support_off", "/support_add", "/support_del", "/support_list",
    "/ad_on", "/ad_off", "/ad_set", "/ad_interval", "/ad_status",
    "/setwelcome",
    "/clear_cache",
    "/welcome_ttl",
    "/antispam_on", "/antispam_off",
}

# ====== LOCAL MODELS ======
from core.models import (
    init_db, SessionLocal, Setting, Filter, Whitelist,
    User, count_users, Warning, Blacklist,
    Supporter, SupportSetting, list_supporters, get_support_enabled
)

# ====== I18N ======
from core.lang import t, LANG

# ====== KEEP ALIVE WEB ======
from keep_alive_server import keep_alive

# === Helper lấy user từ reply hoặc tham số ===
def _get_target_user(update: Update, args) -> tuple[int | None, str]:
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

# ====== STATE ======
FLOOD = {}

# ---------------- URL/DOMAIN HELPERS ----------------
LINK_RE = re.compile(
    r"(https?://[^\s<>()]+|www\.[^\s<>()]+|t\.me/[^\s<>()]+|@\w+|[a-zA-Z0-9-]+\.(com|net|org|vn|xyz|info|io|co|biz|me|app|site|top|store|ru|cn|uk|us)(/[^\s<>()]+)?)",
    re.IGNORECASE
)
URL_RE = re.compile(r"(https?://[^\s<>()]+|www\.[^\s<>()]+|t\.me/[^\s<>()]+)", re.IGNORECASE)
DOMAIN_RE = re.compile(r"\b([a-z0-9][a-z0-9\-\.]+\.[a-z]{2,})\b", re.IGNORECASE)
MENTION_RE = re.compile(r"(?<!\w)@\w+", re.IGNORECASE)
TRAILING_PUNCT_RE = re.compile(r"[),.;!?]+$")

def to_host(domain_or_url: str) -> str:
    s = (domain_or_url or "").strip().lower()
    if not s:
        return ""
    s = TRAILING_PUNCT_RE.sub("", s)
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0].split("?")[0].split("#")[0].strip()
    if s.startswith("www."):
        s = s[4:]
    return s

def extract_hosts(text: str) -> list[str]:
    text = (text or "").strip()
    hosts = []
    for url in URL_RE.findall(text):
        hosts.append(to_host(url))
    for dom in DOMAIN_RE.findall(text):
        hosts.append(to_host(dom))
    out, seen = [], set()
    for h in hosts:
        if h and h not in seen:
            out.append(h); seen.add(h)
    return out

def host_allowed(host: str, allow_list: list[str]) -> bool:
    h = to_host(host)
    for d in allow_list:
        dd = to_host(d)
        if dd and (h == dd or h.endswith("." + dd)):
            return True
    return False

def remove_links(text: str) -> str:
    return re.sub(LINK_RE, "[link bị xóa]", text or "")

# ====== PRO modules (an toàn nếu thiếu) ======
try:
    from pro.handlers import register_handlers, register_clear_cache
except Exception as e:
    print("pro.handlers warn:", e)
    register_handlers = lambda app, **kw: None
    register_clear_cache = lambda app: None

try:
    from pro.scheduler import attach_scheduler
except Exception as e:
    print("pro.scheduler warn:", e)
    attach_scheduler = lambda app: None

# ====== UPTIME ======
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
def get_settings(*args, **kwargs) -> Setting:
    if len(args) == 1 and isinstance(args[0], int):
        chat_id = args[0]
        db = SessionLocal()
        try:
            s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
            if not s:
                s = Setting(
                    chat_id=chat_id,
                    antilink=True, antimention=True, antiforward=True,
                    flood_limit=3, flood_mode="mute",
                )
                db.add(s); db.commit()
            return s
        finally:
            db.close()
    if len(args) == 2:
        db, chat_id = args
        s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
        if not s:
            s = Setting(
                chat_id=chat_id,
                antilink=True, antimention=True, antiforward=True,
                flood_limit=3, flood_mode="mute",
            )
            db.add(s); db.commit()
        return s
    raise TypeError("get_settings() expected (chat_id) or (db, chat_id)")

# ====== ADMIN CHECK ======
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

# ====== Chọn ngôn ngữ ======
USER_LANG = {}  # {user_id: "vi"|"en"}

async def on_lang_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        db.add(u); db.commit()
    total = count_users(); db.close()

    lang = USER_LANG.get(user.id, "vi")
    hello = t(lang, "start", name=user.first_name, count=total)
    msg = (
        "🤖 <b>HotroSecurityBot</b>\n\n"
        f"{hello}\n\n"
        f"{'Gõ /help để xem danh sách lệnh 💬' if lang=='vi' else 'Type /help to see all commands 💬'}"
    )
    keyboard = [[InlineKeyboardButton("Languages", callback_data="lang_menu")]]
    await m.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

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

# ====== STATS / STATUS ======
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

# ====== PRO: /warn ======
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

    wl_hosts = [w.domain for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
    msg_hosts = extract_hosts(text)
    if any(host_allowed(h, wl_hosts) for h in msg_hosts):
        db.close()
        return await msg.reply_text("Domain này nằm trong whitelist, không cảnh báo.")

    try:
        await target_msg.delete()
    except Exception:
        pass

    safe_text = remove_links(text)
    try:
        await context.bot.send_message(chat_id, f"🔒 Tin đã xóa link: {safe_text}")
    except Exception:
        pass

    w = db.query(Warning).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
    if not w:
        w = Warning(chat_id=chat_id, user_id=target_user.id, count=1)
        db.add(w)
    else:
        w.count += 1
        w.last_warned = datetime.now(timezone.utc)
    db.commit()

    await context.bot.send_message(
        chat_id,
        f"⚠️ <b>Cảnh báo:</b> <a href='tg://user?id={target_user.id}'>Người này</a> đã chia sẻ link không được phép. ({w.count}/3)",
        parse_mode=ParseMode.HTML
    )

    try:
        if 3 <= w.count < 5:
            until = datetime.now(timezone.utc) + timedelta(hours=24)
            await context.bot.restrict_chat_member(
                chat_id, target_user.id,
                ChatPermissions(can_send_messages=False),
                until_date=until
            )
            await context.bot.send_message(chat_id, "🚫 Người này bị cấm 24h do vi phạm nhiều lần (>=3).")
        elif w.count >= 5:
            await context.bot.ban_chat_member(chat_id, target_user.id)
            await context.bot.send_message(chat_id, "⛔️ Người này đã bị kick khỏi nhóm do tái phạm quá nhiều lần (>=5).")
            bl = db.query(Blacklist).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
            if not bl:
                db.add(Blacklist(chat_id=chat_id, user_id=target_user.id))
                db.commit()
            await context.bot.send_message(
                chat_id,
                f"🚫 <b>Đã đưa vào danh sách đen:</b> <a href='tg://user?id={target_user.id}'>Người này</a>.",
                parse_mode=ParseMode.HTML
            )
    except Exception:
        pass

    db.close()

# ====== WHITELIST ======
async def wl_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    m = update.effective_message
    if not context.args:
        return await m.reply_text("Cú pháp: /wl_add <domain>")
    raw = context.args[0]
    domain = to_host(raw)
    if not domain:
        return await m.reply_text("Domain không hợp lệ.")
    db = SessionLocal()
    try:
        chat_id = update.effective_chat.id
        ex = db.query(Whitelist).filter_by(chat_id=chat_id, domain=domain).one_or_none()
        if ex:
            return await m.reply_text(f"Domain đã có trong whitelist: {domain}")
        db.add(Whitelist(chat_id=chat_id, domain=domain))
        db.commit()
        total = db.query(Whitelist).filter_by(chat_id=chat_id).count()
        await m.reply_text(f"✅ Đã thêm whitelist: {domain}\nTổng whitelist của nhóm: {total}")
    finally:
        db.close()

async def wl_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    db = SessionLocal()
    try:
        items = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id).all()
        if not items:
            await update.effective_message.reply_text("Danh sách trống.")
            return
        await update.effective_message.reply_text("\n".join(f"• {w.domain}" for w in items))
    finally:
        db.close()

async def wl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    m = update.effective_message
    if not context.args:
        return await m.reply_text("Cú pháp: /wl_del <domain>")
    raw = context.args[0]
    domain = to_host(raw)
    if not domain:
        return await m.reply_text("Domain không hợp lệ.")
    db = SessionLocal()
    try:
        chat_id = update.effective_chat.id
        row = db.query(Whitelist).filter_by(chat_id=chat_id, domain=domain).one_or_none()
        if not row:
            await m.reply_text("❗Không tìm thấy domain trong whitelist.\n💡Hãy thử /wl_list để xem danh sách hiện tại.")
            return
        db.delete(row)
        db.commit()
        await m.reply_text(f"🗑️ Đã xoá khỏi whitelist: {domain}")
    finally:
        db.close()

# ====== WARN INFO / CLEAR / TOP ======
async def warn_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    uid, name = _get_target_user(update, context.args)
    if not uid:
        return await update.effective_message.reply_text("Reply tin nhắn hoặc dùng: /warn_info <user_id>")
    db = SessionLocal()
    try:
        row = db.query(Warning).filter_by(chat_id=chat_id, user_id=uid).one_or_none()
        count = row.count if row else 0
        await update.effective_message.reply_text(f"⚠️ {name} hiện có {count} cảnh cáo.")
    finally:
        db.close()

async def warn_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    chat_id = update.effective_chat.id
    uid, name = _get_target_user(update, context.args)
    if not uid:
        return await update.effective_message.reply_text("Reply tin nhắn hoặc dùng: /warn_clear <user_id>")
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
    chat_id = update.effective_chat.id
    db = SessionLocal()
    try:
        rows = (
            db.query(Warning)
              .filter_by(chat_id=chat_id)
              .order_by(Warning.count.desc())
              .limit(10).all()
        )
        if not rows:
            return await update.effective_message.reply_text("Chưa có ai bị cảnh cáo.")
        lines = [f"{i+1}. user_id {r.user_id}: {r.count} cảnh cáo" for i, r in enumerate(rows)]
        await update.effective_message.reply_text("🏆 Top cảnh cáo:\n" + "\n".join(lines))
    finally:
        db.close()

# ====== FILTERS & TOGGLES ======
async def filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    if not context.args:
        return await update.effective_message.reply_text(
            "Cú pháp: <code>/filter_add từ_khoá</code>", parse_mode=ParseMode.HTML
        )
    pattern = " ".join(context.args).strip()
    if not pattern:
        return await update.effective_message.reply_text("Từ khoá rỗng.")
    db = SessionLocal()
    try:
        f = Filter(chat_id=update.effective_chat.id, pattern=pattern)
        db.add(f)
        db.commit()
        await update.effective_message.reply_text(
            f"✅ Đã thêm filter #{f.id}: <code>{pattern}</code>", parse_mode=ParseMode.HTML
        )
    finally:
        db.close()

async def filter_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    db = SessionLocal()
    try:
        items = db.query(Filter).filter_by(chat_id=update.effective_chat.id).all()
        if not items:
            return await update.effective_message.reply_text("Danh sách filter trống.")
        out = ["<b>Filters:</b>"] + [f"{i.id}. <code>{i.pattern}</code>" for i in items]
        await update.effective_message.reply_text("\n".join(out), parse_mode=ParseMode.HTML)
    finally:
        db.close()

async def filter_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    if not context.args:
        return await update.effective_message.reply_text("Cú pháp: /filter_del <id>")
    try:
        fid = int(context.args[0])
    except ValueError:
        return await update.effective_message.reply_text("ID không hợp lệ.")
    db = SessionLocal()
    try:
        it = db.query(Filter).filter_by(id=fid, chat_id=update.effective_chat.id).one_or_none()
        if not it:
            return await update.effective_message.reply_text("Không tìm thấy ID.")
        db.delete(it)
        db.commit()
        await update.effective_message.reply_text(f"🗑️ Đã xoá filter #{fid}.")
    finally:
        db.close()

async def _toggle(update: Update, field: str, val: bool, label: str):
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = Setting(chat_id=update.effective_chat.id)
            db.add(s)
        setattr(s, field, val)
        db.commit()
        await update.effective_message.reply_text(("✅ Bật " if val else "❎ Tắt ") + label + ".")
    finally:
        db.close()

async def antilink_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context): return
    await _toggle(update, "antilink", True, "Anti-link")

async def antilink_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context): return
    await _toggle(update, "antilink", False, "Anti-link")

async def antimention_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context): return
    await _toggle(update, "antimention", True, "Anti-mention")

async def antimention_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context): return
    await _toggle(update, "antimention", False, "Anti-mention")

async def antiforward_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context): return
    await _toggle(update, "antiforward", True, "Anti-forward")

async def antiforward_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context): return
    await _toggle(update, "antiforward", False, "Anti-forward")

async def setflood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context): return
    if not context.args:
        return await update.effective_message.reply_text("Cú pháp: /setflood <số tin>")
    try:
        n = max(2, int(context.args[0]))
    except ValueError:
        return await update.effective_message.reply_text("Giá trị không hợp lệ.")
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = Setting(chat_id=update.effective_chat.id)
            db.add(s)
        s.flood_limit = n
        db.commit()
        await update.effective_message.reply_text(f"✅ Flood limit = {n}")
    finally:
        db.close()

async def nobots_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    db = SessionLocal()
    try:
        s = get_settings(db, update.effective_chat.id)
        s.nobots = True
        db.commit()
        await update.effective_message.reply_text("✅ Đã bật chặn bot khi có thành viên mới.")
    finally:
        db.close()

async def nobots_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    db = SessionLocal()
    try:
        s = get_settings(db, update.effective_chat.id)
        s.nobots = False
        db.commit()
        await update.effective_message.reply_text("❎ Đã tắt chặn bot khi có thành viên mới.")
    finally:
        db.close()

async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if not getattr(msg, "new_chat_members", None):
        return
    db = SessionLocal()
    try:
        s = get_settings(db, chat.id)
        if not s.nobots:
            return
        for m in msg.new_chat_members:
            if m.is_bot:
                try:
                    await context.bot.ban_chat_member(chat.id, m.id)
                    await msg.reply_text(
                        f"🤖 Đã xoá bot <b>{m.first_name}</b> (nobots đang bật).",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    print("Kick bot failed:", e)
    finally:
        db.close()

# ===== ANTISPAM (RAM) =====
ANTISPAM_CHATS: set[int] = set()

async def antispam_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    ANTISPAM_CHATS.add(update.effective_chat.id)
    await update.effective_message.reply_text("✅ Đã bật chống spam ảnh & media.")

async def antispam_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    ANTISPAM_CHATS.discard(update.effective_chat.id)
    await update.effective_message.reply_text("❎ Đã tắt chống spam ảnh & media.")
# ===== AUTO BAN / MUTE =====
async def _autoban_enforce(db, context, chat_id: int, user_id: int):
    cfg = get_or_create_autoban(db, chat_id)
    if not cfg.enabled:
        return
    w = db.query(Warning).filter_by(chat_id=chat_id, user_id=user_id).one_or_none()
    count = (w.count if w else 0)
    # mute khi đạt warn_threshold
    if count >= cfg.warn_threshold and count < cfg.ban_threshold:
        try:
            until = datetime.now(timezone.utc) + timedelta(minutes=cfg.mute_minutes)
            await context.bot.restrict_chat_member(
                chat_id, user_id,
                ChatPermissions(can_send_messages=False),
                until_date=until
            )
            await context.bot.send_message(
                chat_id,
                f"🤐 Đã mute <a href='tg://user?id={user_id}'>user</a> {cfg.mute_minutes} phút (tự động).",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
    # ban khi đạt ban_threshold
    if count >= cfg.ban_threshold:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            db.add(Blacklist(chat_id=chat_id, user_id=user_id))
            db.commit()
            await context.bot.send_message(
                chat_id,
                f"⛔️ Đã ban <a href='tg://user?id={user_id}'>user</a> (tự động).",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
# ====== Guard (lọc tin nhắn thường) ======
async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    chat = update.effective_chat
    user = update.effective_user
    text = (msg.text or msg.caption or "")
    low = text.lower()

    # --- AntiSpam: chặn media với member, trừ ảnh báo lỗi ---
    if chat and chat.id in ANTISPAM_CHATS:
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            is_admin = member.status in ("administrator", "creator")
        except Exception:
            is_admin = False

        if not is_admin:
            text_lower = (msg.caption or msg.text or "").lower()
            if any(kw in text_lower for kw in ["lỗi", "bug", "error", "report"]):
                return
            has_media = any([
                getattr(msg, "photo", None),
                getattr(msg, "video", None),
                getattr(msg, "animation", None),
                getattr(msg, "sticker", None),
                (getattr(msg, "document", None) and
                 not msg.document.file_name.lower().endswith((".txt", ".md", ".csv"))),
                getattr(msg, "voice", None),
                getattr(msg, "audio", None),
            ])
            if has_media:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

    # 1) Chặn lệnh giả
    if text.startswith("/"):
        cmd = text.split()[0].lower()
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            is_admin = member.status in ("administrator", "creator")
        except Exception:
            is_admin = False

        if not is_admin and cmd not in ALLOWED_COMMANDS:
            try: await msg.delete()
            except Exception: pass
            return
        return  # để CommandHandler xử lý tiếp

    # 2) Lọc nội dung thường
    chat_id = chat.id
    db = SessionLocal()
    try:
        s = get_settings(db, chat_id)

        # 2.1. Từ khóa filter
        for it in db.query(Filter).filter_by(chat_id=chat_id).all():
            if it.pattern and it.pattern.lower() in low:
                try: await msg.delete()
                except Exception: pass
                return

        # 2.2. Chặn tin nhắn forward
        if s.antiforward and getattr(msg, "forward_origin", None):
            try: await msg.delete()
            except Exception: pass
            return

        # 2.3. Chặn link (TRỪ whitelist hoặc supporter)
        if s.antilink and LINK_RE.search(text):
            wl_hosts  = [to_host(w.domain) for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
            msg_hosts = extract_hosts(text)

            if any(host_allowed(h, wl_hosts) for h in msg_hosts):
                return  # nằm trong whitelist

            allow_support = False
            try:
                if get_support_enabled(db, chat_id):
                    sup_ids = list_supporters(db, chat_id)
                    allow_support = (user.id in sup_ids)
            except Exception:
                allow_support = False

            if not allow_support:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        # 2.4. Chặn mention (loại URL trước rồi mới bắt @username)
        if s.antimention:
            text_no_urls = URL_RE.sub("", text)
            if MENTION_RE.search(text_no_urls):
                try: await msg.delete()
                except Exception: pass
                return

        # 2.5. Chống flood nhẹ
        key = (chat_id, user.id)
        now_ts = datetime.now(timezone.utc).timestamp()
        bucket = [t for t in FLOOD.get(key, []) if now_ts - t < 10]
        bucket.append(now_ts)
        FLOOD[key] = bucket
        if len(bucket) > s.flood_limit and s.flood_mode == "mute":
            try:
                until = datetime.now(timezone.utc) + timedelta(minutes=5)
                await context.bot.restrict_chat_member(
                    chat_id, user.id,
                    ChatPermissions(can_send_messages=False),
                    until_date=until
                )
            except Exception:
                pass
    finally:
        db.close()
log_violation(db, chat_id, user.id, "filter", text)  # ghi log
w = db.query(Warning).filter_by(chat_id=chat_id, user_id=user.id).one_or_none()
if not w:
    w = Warning(chat_id=chat_id, user_id=user.id, count=1); db.add(w)
else:
    w.count += 1
db.commit()
await _autoban_enforce(db, context, chat_id, user.id)
# ====== Chặn lệnh không hợp lệ ======
async def block_unknown_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    text = (msg.text or "").strip()
    if not text.startswith("/"):
        return
    cmd = text.split()[0].split("@")[0].lower()
    if cmd not in {c.lower() for c in ALLOWED_COMMANDS}:
        try:
            await msg.delete()
        except Exception:
            pass

# ====== Error log ======
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, Conflict):
        print("Conflict ignored (another instance was running).")
        return
    err = repr(context.error)
    print("ERROR:", err)
    try:
        if OWNER_ID:
            await context.bot.send_message(OWNER_ID, f"⚠️ Error:\n<code>{err}</code>", parse_mode=ParseMode.HTML)
    except Exception as e:
        print("owner notify fail:", e)

# ===== Startup hook =====
async def on_startup(app: Application):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("Webhook cleared, using polling mode.")
    except Exception as e:
        print("delete_webhook warn:", e)
    try:
        me = await app.bot.get_me()
        app.bot_data["contact"] = me.username or CONTACT_USERNAME
    except Exception:
        app.bot_data["contact"] = CONTACT_USERNAME or "admin"
    if OWNER_ID:
        try:
            await app.bot.send_message(
                OWNER_ID, "🔁 Bot restarted và đang hoạt động!\n⏱ Uptime 0s\n✅ Ready."
            )
        except Exception as e:
            print("⚠️ Notify owner failed:", e)

# ✅ Lệnh cài đặt lời chào
async def setwelcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    if not context.args:
        return await update.effective_message.reply_text(
            "📌 Dùng: /setwelcome <câu chào>. Dùng {name} để thay tên thành viên."
        )
    content = " ".join(context.args).strip()
    set_welcome_message(update.effective_chat.id, content)
    await update.effective_message.reply_text("✅ Đã lưu câu chào thành công!")

# 👋 Gửi lời chào khi có thành viên mới + auto-delete theo TTL
import asyncio  # đặt ở đầu file nếu chưa có

async def _delete_later(bot, chat_id: int, message_id: int, ttl: int):
    await asyncio.sleep(ttl)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

async def welcome_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # an toàn với event không có message
    if not getattr(update, "message", None) or not update.message.new_chat_members:
        return

    chat_id = update.effective_chat.id
    welcome_text = get_welcome_message(chat_id)
    if not welcome_text:
        return

    # lấy TTL tự xoá
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
        ttl = int(getattr(s, "welcome_ttl", 0) or 0)
    finally:
        db.close()

    # gửi tin CHÀO MỚI (không reply vào “đã tham gia”)
    for user in update.message.new_chat_members:
        name = user.mention_html() if user else "bạn mới"
        try:
            sent = await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_text.replace("{name}", name),
                parse_mode=ParseMode.HTML
            )
            if ttl > 0:
                context.application.create_task(
                    _delete_later(context.bot, sent.chat.id, sent.message_id, ttl)
                )
        except Exception:
            # tránh crash nếu bot không có quyền gửi/xoá
            pass

# ✅ Đặt thời gian tự xoá lời chào (0 = không xoá)
async def welcome_ttl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _must_admin_in_group(update, context):
        return
    if not context.args:
        return await update.effective_message.reply_text(
            "Cú pháp: /welcome_ttl <giây> (0 = không xoá)"
        )
    try:
        ttl = max(0, int(context.args[0]))
    except ValueError:
        return await update.effective_message.reply_text("Giá trị không hợp lệ.")
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = Setting(chat_id=update.effective_chat.id)
            db.add(s)
        s.welcome_ttl = ttl
        db.commit()
        await update.effective_message.reply_text(
            f"✅ Đã đặt thời gian tự xoá lời chào = {ttl} giây."
        )
    finally:
        db.close()

# ====== Main ======
def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ Missing BOT_TOKEN")

    print("🚀 Booting bot...")
    init_db()

    try:
        keep_alive()
    except Exception as e:
        print("Lỗi keep_alive:", e)

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = on_startup
    app.add_error_handler(on_error)

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lang", lang_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("uptime", uptime_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("setwelcome", setwelcome_cmd))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_member))

    # FREE whitelist
    app.add_handler(CommandHandler("wl_add", wl_add))
    app.add_handler(CommandHandler("wl_list", wl_list))
    app.add_handler(CommandHandler("wl_del", wl_del))

    # Filters & toggles
    app.add_handler(CommandHandler("filter_add", filter_add))
    app.add_handler(CommandHandler("filter_list", filter_list))
    app.add_handler(CommandHandler("filter_del", filter_del))
    app.add_handler(CommandHandler("antilink_on", antilink_on))
    app.add_handler(CommandHandler("antilink_off", antilink_off))
    app.add_handler(CommandHandler("antimention_on", antimention_on))
    app.add_handler(CommandHandler("antimention_off", antimention_off))
    app.add_handler(CommandHandler("antiforward_on", antiforward_on))
    app.add_handler(CommandHandler("antiforward_off", antiforward_off))
    app.add_handler(CommandHandler("setflood", setflood))
    app.add_handler(CommandHandler("nobots_on", nobots_on))
    app.add_handler(CommandHandler("nobots_off", nobots_off))
    app.add_handler(CommandHandler("welcome_ttl", welcome_ttl_cmd))
    app.add_handler(CommandHandler("antispam_on", antispam_on))
    app.add_handler(CommandHandler("antispam_off", antispam_off))

    # Warn utilities
    app.add_handler(CommandHandler("warn", warn_cmd))
    app.add_handler(CommandHandler("warn_info", warn_info))
    app.add_handler(CommandHandler("warn_clear", warn_clear))
    app.add_handler(CommandHandler("warn_top", warn_top))

    # PRO (an toàn nếu thiếu)
    register_handlers(app, owner_id=OWNER_ID)
    attach_scheduler(app)
    register_clear_cache(app)

    # Inline buttons: Languages
    app.add_handler(CallbackQueryHandler(on_lang_button, pattern=r"^lang_(menu|vi|en)$"))

    # Chặn mọi lệnh không được cho phép
    app.add_handler(MessageHandler(filters.COMMAND, block_unknown_commands))

    # Guard: lọc tin nhắn thường
    app.add_handler(MessageHandler(~filters.StatusUpdate.ALL & ~filters.COMMAND, guard))

    # Lắng nghe thành viên mới vào nhóm để đá bot khi cần
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))

    print("✅ Bot started, polling Telegram updates...")
    app.run_polling(drop_pending_updates=True, timeout=60)

# ====== Entry point ======
if __name__ == "__main__":
    main()
