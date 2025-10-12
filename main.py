# main.py
import sys
sys.modules.pop("core.models", None)  # tránh import vòng khi redeploy

import os, re
from datetime import datetime, timezone, timedelta
from sqlalchemy import func

from telegram import Update, ChatPermissions
from telegram.constants import ParseMode
from telegram.error import Conflict
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ====== I18N ======
from core.lang import t

# Lưu lựa chọn ngôn ngữ trong RAM (user và/hoặc chat)
LANG_PREF_USER: dict[int, str] = {}   # {user_id: "vi"|"en"}
LANG_PREF_CHAT: dict[int, str] = {}   # {chat_id: "vi"|"en"}

def _get_lang(update: Update) -> str:
    """Ưu tiên: cài cho chat -> cài cho user -> 'vi'."""
    uid = update.effective_user.id if update.effective_user else 0
    cid = update.effective_chat.id if update.effective_chat else 0
    return LANG_PREF_CHAT.get(cid) or LANG_PREF_USER.get(uid) or "vi"

# ====== LOCAL MODELS ======
from core.models import (
    init_db, SessionLocal, Setting, Filter, Whitelist,
    User, count_users, Warning, Blacklist
)

# ====== KEEP ALIVE WEB ======
from keep_alive_server import keep_alive

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

# ====== PRO modules (an toàn nếu thiếu) ======
try:
    from pro.handlers import register_handlers
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

# ====== Text blocks (help) ======
HELP_VI = (
    "🎯 <b>HotroSecurityBot – Hỗ trợ quản lý nhóm Telegram</b>\n"
    "Tự động lọc spam, chặn link, cảnh báo vi phạm và quản lý quảng cáo thông minh.\n\n"

    "🆓 <b>GÓI FREE</b>\n"
    "• /filter_add &lt;từ&gt; – Thêm từ khoá cần chặn\n"
    "• /filter_list – Xem danh sách từ khoá đã chặn\n"
    "• /filter_del &lt;id&gt; – Xoá filter theo ID\n"
    "• /antilink_on | /antilink_off – Bật/tắt chặn link\n"
    "• /antimention_on | /antimention_off – Bật/tắt chặn tag @all / mention\n"
    "• /antiforward_on | /antiforward_off – Bật/tắt chặn tin chuyển tiếp\n"
    "• /setflood &lt;n&gt; – Giới hạn spam tin nhắn (mặc định 3)\n\n"

    "💎 <b>GÓI PRO</b>\n"
    "• /pro – Mở bảng hướng dẫn dùng thử & kích hoạt PRO\n"
    "• /trial – Dùng thử miễn phí 7 ngày\n"
    "• /redeem &lt;key&gt; – Kích hoạt key PRO\n"
    "• /genkey &lt;days&gt; – (OWNER) Tạo key PRO thời hạn tuỳ chọn\n"
    "• /wl_add &lt;domain&gt; | /wl_del &lt;domain&gt; | /wl_list – Quản lý whitelist link được phép gửi\n"
    "• /warn – (Admin) Trả lời vào tin có link để cảnh báo / xoá link / tự động chặn khi vi phạm 3 lần\n\n"

    "📢 <b>QUẢNG CÁO TỰ ĐỘNG</b>\n"
    "• /ad_on – Bật quảng cáo tự động\n"
    "• /ad_off – Tắt quảng cáo tự động\n"
    "• /ad_set &lt;nội dung&gt; – Nội dung quảng cáo\n"
    "• /ad_interval &lt;phút&gt; – Chu kỳ gửi (mặc định 60)\n"
    "• /ad_status – Xem trạng thái quảng cáo\n\n"

    "🌐 <b>Ngôn ngữ</b>\n"
    "• /lang vi – Tiếng Việt | /lang en – English\n\n"

    "⚙️ <b>HỖ TRỢ</b>\n"
    f"• Liên hệ @{CONTACT_USERNAME or 'Myyduyenng'} để mua key PRO hoặc hỗ trợ kỹ thuật.\n"
    "🚀 <i>Cảm ơn bạn đã sử dụng HotroSecurityBot!</i>"
)

HELP_EN = (
    "🎯 <b>HotroSecurityBot – Group security assistant</b>\n"
    "Auto anti-spam, link blocking, warning, and smart promo management.\n\n"

    "🆓 <b>FREE</b>\n"
    "• /filter_add &lt;word&gt; – Add banned keyword\n"
    "• /filter_list – List banned keywords\n"
    "• /filter_del &lt;id&gt; – Delete a filter by ID\n"
    "• /antilink_on | /antilink_off – Toggle link blocking\n"
    "• /antimention_on | /antimention_off – Toggle @all/mentions blocking\n"
    "• /antiforward_on | /antiforward_off – Toggle forwarded messages blocking\n"
    "• /setflood &lt;n&gt; – Flood limit (default 3)\n\n"

    "💎 <b>PRO</b>\n"
    "• /pro – How to try & activate PRO\n"
    "• /trial – 7-day free trial\n"
    "• /redeem &lt;key&gt; – Redeem PRO key\n"
    "• /genkey &lt;days&gt; – (OWNER) Generate a key\n"
    "• /wl_add &lt;domain&gt; | /wl_del &lt;domain&gt; | /wl_list – Whitelist allowed links\n"
    "• /warn – (Admin) Reply to a message with a link to warn/delete; auto block after 3 strikes\n\n"

    "📢 <b>AUTO PROMOTION</b>\n"
    "• /ad_on – Enable auto-promotion\n"
    "• /ad_off – Disable auto-promotion\n"
    "• /ad_set &lt;text&gt; – Set promo content\n"
    "• /ad_interval &lt;minutes&gt; – Interval (default 60)\n"
    "• /ad_status – Show promo status\n\n"

    "🌐 <b>Language</b>\n"
    "• /lang vi – Vietnamese | /lang en – English\n\n"

    "⚙️ <b>SUPPORT</b>\n"
    f"• Contact @{CONTACT_USERNAME or 'Myyduyenng'} for PRO keys & support.\n"
    "🚀 <i>Thanks for using HotroSecurityBot!</i>"
)

# ====== Commands FREE ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = SessionLocal()
    u = db.get(User, user.id)
    if not u:
        u = User(id=user.id, username=user.username or "")
        db.add(u); db.commit()
    total = count_users()
    lang = _get_lang(update)
    msg = (
        "🤖 <b>HotroSecurityBot</b>\n\n" +
        t(lang, "start", name=user.first_name, count=total) +
        ("\n\nType /help to see commands 💬" if lang == "en" else "\n\nGõ /help để xem danh sách lệnh 💬")
    )
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode=ParseMode.HTML)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _get_lang(update)
    txt = HELP_EN if lang == "en" else HELP_VI
    await context.bot.send_message(
        update.effective_chat.id, txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )

# ---- /lang command (vi|en) ----
async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Ngôn ngữ hiện tại: " + _get_lang(update) + "\n/set language: /lang vi | /lang en"
            if _get_lang(update) != "en"
            else "Current language: en\nSet language: /lang vi | /lang en"
        )
    choice = context.args[0].lower()
    if choice not in ("vi", "en"):
        return await update.message.reply_text("Use: /lang vi | /lang en")
    # lưu theo chat (group) nếu là group, còn private thì theo user
    if update.effective_chat.type in ("group", "supergroup"):
        LANG_PREF_CHAT[update.effective_chat.id] = choice
    else:
        LANG_PREF_USER[update.effective_user.id] = choice
    await update.message.reply_text("Đã đổi ngôn ngữ." if choice == "vi" else "Language updated.")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = count_users()
    lang = _get_lang(update)
    text = f"📊 Total users: {total:,}" if lang == "en" else f"📊 Tổng người dùng bot: {total:,}"
    await update.message.reply_text(text)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t0 = datetime.now(timezone.utc)
    lang = _get_lang(update)
    m = await update.message.reply_text("⏳ Measuring ping…" if lang == "en" else "⏳ Đang đo ping…")
    dt = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    up = datetime.now(timezone.utc) - START_AT
    text = (
        f"✅ Online | 🕒 Uptime: {_fmt_td(up)} | 🏓 Ping: {dt:.0f} ms"
        if lang == "vi" else
        f"✅ Online | 🕒 Uptime: {_fmt_td(up)} | 🏓 Ping: {dt:.0f} ms"
    )
    await m.edit_text(text)

# ====== UPTIME / PING ======
async def uptime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    up = datetime.now(timezone.utc) - START_AT
    lang = _get_lang(update)
    await update.message.reply_text(
        f"⏱ Uptime: {_fmt_td(up)}" if lang == "en" else f"⏱ Uptime: {_fmt_td(up)}"
    )

async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t0 = datetime.now(timezone.utc)
    m = await update.message.reply_text("Pinging…")
    dt = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    await m.edit_text(f"🏓 Pong: {dt:.0f} ms")

# ====== PRO: Admin reply → /warn ======
async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    admin_user = update.effective_user
    lang = _get_lang(update)

    if not msg.reply_to_message:
        return await msg.reply_text("Reply to the message with a link then type /warn"
                                    if lang == "en" else "Hãy reply vào tin có link rồi gõ /warn")

    try:
        member = await context.bot.get_chat_member(chat_id, admin_user.id)
        if member.status not in ("administrator", "creator"):
            return await msg.reply_text("Admins only." if lang == "en" else "Chỉ admin mới dùng lệnh này.")
    except Exception:
        return await msg.reply_text("Cannot check admin rights." if lang == "en" else "Không thể kiểm tra quyền admin.")

    target_msg = msg.reply_to_message
    target_user = target_msg.from_user
    text = (target_msg.text or target_msg.caption or "")

    if not LINK_RE.search(text):
        return await msg.reply_text("Replied message has no link." if lang == "en" else "Tin được reply không chứa link.")

    db = SessionLocal()

    wl = [w.domain for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
    if any(d and d.lower() in text.lower() for d in wl):
        db.close()
        return await msg.reply_text("This domain is whitelisted."
                                    if lang == "en" else "Domain này nằm trong whitelist, không cảnh báo.")

    try:
        await target_msg.delete()
    except Exception:
        pass

    safe_text = remove_links(text)
    try:
        await context.bot.send_message(chat_id,
            f"🔒 Removed link: {safe_text}" if lang == "en" else f"🔒 Tin đã xóa link: {safe_text}")
    except Exception:
        pass

    w = db.query(Warning).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
    if not w:
        w = Warning(chat_id=chat_id, user_id=target_user.id, count=1); db.add(w)
    else:
        w.count += 1; w.last_warned = func.now()
    db.commit()

    await context.bot.send_message(
        chat_id,
        (f"⚠️ <b>Warning:</b> <a href='tg://user?id={target_user.id}'>User</a> shared a disallowed link. ({w.count}/3)")
        if lang == "en" else
        (f"⚠️ <b>Cảnh báo:</b> <a href='tg://user?id={target_user.id}'>Người này</a> đã chia sẻ link không được phép. ({w.count}/3)"),
        parse_mode=ParseMode.HTML
    )

    if w.count >= 3:
        bl = db.query(Blacklist).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
        if not bl:
            db.add(Blacklist(chat_id=chat_id, user_id=target_user.id))
        db.commit()

        await context.bot.send_message(
            chat_id,
            f"🚫 <b>Blacklisted:</b> <a href='tg://user?id={target_user.id}'>User</a>."
            if lang == "en" else
            f"🚫 <b>Đã đưa vào danh sách đen:</b> <a href='tg://user?id={target_user.id}'>Người này</a>.",
            parse_mode=ParseMode.HTML
        )

        try:
            until = datetime.now(timezone.utc) + timedelta(days=365*10)
            await context.bot.restrict_chat_member(
                chat_id, target_user.id,
                ChatPermissions(can_send_messages=False),
                until_date=until
            )
        except Exception:
            pass

    db.close()

# ====== Guard (lọc tin nhắn thường) ======
async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    if msg.text and msg.text.startswith("/"):
        return

    chat_id = update.effective_chat.id
    text = (msg.text or msg.caption or "")

    db = SessionLocal()
    s = get_settings(chat_id)

    for it in db.query(Filter).filter_by(chat_id=chat_id).all():
        if it.pattern and it.pattern.lower() in text.lower():
            try: await msg.delete()
            except Exception: pass
            return

    if s.antiforward and getattr(msg, "forward_origin", None):
        try: await msg.delete()
        except Exception: pass
        return

    if s.antilink and LINK_RE.search(text):
        wl = [w.domain for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
        if not any(d and d.lower() in text.lower() for d in wl):
            try: await msg.delete()
            except Exception: pass
            return

    if s.antimention and "@" in text:
        try: await msg.delete()
        except Exception: pass
        return

    key = (chat_id, msg.from_user.id)
    now_ts = datetime.now(timezone.utc).timestamp()
    bucket = [t for t in FLOOD.get(key, []) if now_ts - t < 10]
    bucket.append(now_ts); FLOOD[key] = bucket
    if len(bucket) > s.flood_limit and s.flood_mode == "mute":
        try:
            until = datetime.now(timezone.utc) + timedelta(minutes=5)
            await context.bot.restrict_chat_member(
                chat_id, msg.from_user.id,
                ChatPermissions(can_send_messages=False),
                until_date=until
            )
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
                OWNER_ID,
                "🔁 Bot restarted và đang hoạt động!\n⏱ Uptime 0s\n✅ Ready."
            )
        except Exception as e:
            print("⚠️ Notify owner failed:", e)

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

    # ===== ĐĂNG KÝ HANDLERS =====
    app.add_handler(CommandHandler("lang", lang_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

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

    app.add_handler(CommandHandler("uptime", uptime_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))

    app.add_handler(CommandHandler("warn", warn_cmd))
    register_handlers(app, owner_id=OWNER_ID)   # PRO handlers
    attach_scheduler(app)                        # Schedulers

    app.add_handler(MessageHandler(~filters.StatusUpdate.ALL & ~filters.COMMAND, guard))

    print("✅ Bot started, polling Telegram updates...")
    app.run_polling(drop_pending_updates=True, timeout=60)

# ====== FILTERS & TOGGLES (KEEP ORIGINAL BLOCK) ======
async def filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Cú pháp: <code>/filter_add từ_khoá</code>", parse_mode="HTML"
        )
    pattern = " ".join(context.args).strip()
    if not pattern:
        return await update.message.reply_text("Từ khoá rỗng.")
    db = SessionLocal()
    try:
        f = Filter(chat_id=update.effective_chat.id, pattern=pattern)
        db.add(f)
        db.commit()
        await update.message.reply_text(
            f"✅ Đã thêm filter #{f.id}: <code>{pattern}</code>", parse_mode="HTML"
        )
    finally:
        db.close()

async def filter_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        items = db.query(Filter).filter_by(chat_id=update.effective_chat.id).all()
        if not items:
            return await update.message.reply_text("Danh sách filter trống.")
        out = ["<b>Filters:</b>"] + [f"{i.id}. <code>{i.pattern}</code>" for i in items]
        await update.message.reply_text("\n".join(out), parse_mode=ParseMode.HTML)
    finally:
        db.close()

async def filter_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /filter_del <id>")
    try:
        fid = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("ID không hợp lệ.")
    db = SessionLocal()
    try:
        it = db.query(Filter).filter_by(id=fid, chat_id=update.effective_chat.id).one_or_none()
        if not it:
            return await update.message.reply_text("Không tìm thấy ID.")
        db.delete(it)
        db.commit()
        await update.message.reply_text(f"🗑️ Đã xoá filter #{fid}.")
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
        await update.message.reply_text(("✅ Bật " if val else "❎ Tắt ") + label + ".")
    finally:
        db.close()

async def antilink_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, "antilink", True, "Anti-link")

async def antilink_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, "antilink", False, "Anti-link")

async def antimention_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, "antimention", True, "Anti-mention")

async def antimention_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, "antimention", False, "Anti-mention")

async def antiforward_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, "antiforward", True, "Anti-forward")

async def antiforward_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, "antiforward", False, "Anti-forward")

async def setflood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /setflood <số tin>")
    try:
        n = max(2, int(context.args[0]))
    except ValueError:
        return await update.message.reply_text("Giá trị không hợp lệ.")
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = Setting(chat_id=update.effective_chat.id)
            db.add(s)
        s.flood_limit = n
        db.commit()
        await update.message.reply_text(f"✅ Flood limit = {n}")
    finally:
        db.close()

# ====== QUẢNG CÁO TỰ ĐỘNG (main side) ======
from core.models import PromoSetting

async def _must_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        return True
    try:
        m = await context.bot.get_chat_member(chat.id, user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

def _get_ps(db, chat_id: int) -> PromoSetting:
    ps = db.query(PromoSetting).filter_by(chat_id=chat_id).one_or_none()
    if not ps:
        ps = PromoSetting(chat_id=chat_id, is_enabled=False, content="", interval_minutes=60, last_sent_at=None)
        db.add(ps); db.commit(); db.refresh(ps)
    return ps

async def ad_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        if not await _must_admin(update, context):
            return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
        if not context.args:
            return await update.message.reply_text("Cú pháp: /ad_set <nội dung>")
        text = " ".join(context.args).strip()
        ps = _get_ps(db, update.effective_chat.id)
        ps.content = text
        db.commit()
        await update.message.reply_text("✅ Đã cập nhật nội dung quảng cáo.")
    finally:
        db.close()

async def ad_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        if not await _must_admin(update, context):
            return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
        if not context.args:
            return await update.message.reply_text("Cú pháp: /ad_interval <phút>")
        try:
            minutes = int(context.args[0])
        except ValueError:
            return await update.message.reply_text("Giá trị phút không hợp lệ.")
        minutes = max(10, minutes)
        ps = _get_ps(db, update.effective_chat.id)
        ps.interval_minutes = minutes
        ps.last_sent_at = None
        db.commit()
        await update.message.reply_text(f"⏱ Chu kỳ quảng cáo: {minutes} phút.")
    finally:
        db.close()

async def ad_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        if not await _must_admin(update, context):
            return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
        ps = _get_ps(db, update.effective_chat.id)
        ps.is_enabled = True
        ps.last_sent_at = None
        db.commit()
        await update.message.reply_text("📢 Đã bật quảng cáo tự động.")
    finally:
        db.close()

async def ad_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        if not await _must_admin(update, context):
            return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
        ps = _get_ps(db, update.effective_chat.id)
        ps.is_enabled = False
        db.commit()
        await update.message.reply_text("🔕 Đã tắt quảng cáo tự động.")
    finally:
        db.close()

async def ad_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        ps = _get_ps(db, update.effective_chat.id)
        last = ps.last_sent_at.isoformat() if ps.last_sent_at else "—"

        msg = (
            "📊 Trạng thái QC:\n"
            "• Bật: {on}\n"
            "• Chu kỳ: {mins} phút\n"
            "• Nội dung: {content}\n"
            "• Lần gửi gần nhất: {last}"
        ).format(
            on="✅" if ps.is_enabled else "❎",
            mins=ps.interval_minutes,
            content=("đã đặt" if ps.content else "—"),
            last=last,
        )

        await update.message.reply_text(msg)
    finally:
        db.close()

# ====== END BLOCK ======

if __name__ == "__main__":
    main()
