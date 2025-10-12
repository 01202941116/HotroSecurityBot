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

# ====== Commands FREE ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = SessionLocal()
    u = db.get(User, user.id)
    if not u:
        u = User(id=user.id, username=user.username or "")
        db.add(u)
        db.commit()
    total = count_users()
    msg = (
        "🤖 <b>HotroSecurityBot</b>\n\n"
        f"Chào <b>{user.first_name}</b> 👋\n"
        f"Hiện có <b>{total:,}</b> người đang sử dụng bot.\n\n"
        "Gõ /help để xem danh sách lệnh 💬"
    )
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode=ParseMode.HTML)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    lang = USER_LANG.get(uid, "vi")
    txt = t(lang, "help_full")
    await context.bot.send_message(
        update.effective_chat.id,
        txt,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

# ====== UPTIME / PING ======
async def uptime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    up = datetime.now(timezone.utc) - START_AT
    await update.message.reply_text(f"⏱ Uptime: {_fmt_td(up)}")

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

    if not msg.reply_to_message:
        return await msg.reply_text("Hãy reply vào tin có link rồi gõ /warn")

    # Chỉ admin/creator được dùng
    try:
        member = await context.bot.get_chat_member(chat_id, admin_user.id)
        if member.status not in ("administrator", "creator"):
            return await msg.reply_text("Chỉ admin mới dùng lệnh này.")
    except Exception:
        return await msg.reply_text("Không thể kiểm tra quyền admin.")

    target_msg = msg.reply_to_message
    target_user = target_msg.from_user
    text = (target_msg.text or target_msg.caption or "")

    # Nếu tin không có link -> bỏ qua
    if not LINK_RE.search(text):
        return await msg.reply_text("Tin được reply không chứa link.")

    db = SessionLocal()

    # link thuộc whitelist -> không xử lý
    wl = [w.domain for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
    if any(d and d.lower() in text.lower() for d in wl):
        db.close()
        return await msg.reply_text("Domain này nằm trong whitelist, không cảnh báo.")

    # Xóa tin gốc & thông báo bản đã loại link
    try:
        await target_msg.delete()
    except Exception:
        pass

    safe_text = remove_links(text)
    try:
        await context.bot.send_message(chat_id, f"🔒 Tin đã xóa link: {safe_text}")
    except Exception:
        pass

    # Cập nhật warning count
    w = db.query(Warning).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
    if not w:
        w = Warning(chat_id=chat_id, user_id=target_user.id, count=1)
        db.add(w)
    else:
        w.count += 1
        w.last_warned = func.now()
    db.commit()

    await context.bot.send_message(
        chat_id,
        f"⚠️ <b>Cảnh báo:</b> <a href='tg://user?id={target_user.id}'>Người này</a> đã chia sẻ link không được phép. ({w.count}/3)",
        parse_mode=ParseMode.HTML
    )

    # đủ 3 lần -> thêm blacklist + (tuỳ chọn) restrict dài hạn
    if w.count >= 3:
        bl = db.query(Blacklist).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
        if not bl:
            db.add(Blacklist(chat_id=chat_id, user_id=target_user.id))
        db.commit()

        await context.bot.send_message(
            chat_id,
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

    # Từ khoá cấm
    for it in db.query(Filter).filter_by(chat_id=chat_id).all():
        if it.pattern and it.pattern.lower() in text.lower():
            try: await msg.delete()
            except Exception: pass
            return

    # Chặn forward
    if s.antiforward and getattr(msg, "forward_origin", None):
        try: await msg.delete()
        except Exception: pass
        return

    # Chặn link (trừ whitelist) — KHÔNG cảnh báo tự động
    if s.antilink and LINK_RE.search(text):
        wl = [w.domain for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
        if not any(d and d.lower() in text.lower() for d in wl):
            try: await msg.delete()
            except Exception: pass
            return

    # Chặn mention
    if s.antimention and "@" in text:
        try: await msg.delete()
        except Exception: pass
        return

    # Kiểm soát flood
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
    # Xoá webhook nếu có (tránh Conflict khi chuyển webhook → polling)
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

    # Thông báo khởi động (tùy chọn)
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

    # giữ Render thức
    try:
        keep_alive()
    except Exception as e:
        print("Lỗi keep_alive:", e)

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = on_startup
    app.add_error_handler(on_error)

    # ===== ĐĂNG KÝ HANDLERS (các hàm PHẢI được định nghĩa bên trên) =====
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lang", lang_cmd))

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
    register_handlers(app, owner_id=OWNER_ID)
    attach_scheduler(app)

    app.add_handler(MessageHandler(~filters.StatusUpdate.ALL & ~filters.COMMAND, guard))

    print("✅ Bot started, polling Telegram updates...")
    app.run_polling(drop_pending_updates=True, timeout=60)
    # ====== FILTERS & TOGGLES (ADD THIS BLOCK) ======
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
        # ====== QUẢNG CÁO TỰ ĐỘNG (HANDLERS) ======
from core.models import PromoSetting

async def _must_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Cho phép ở private; ở group thì phải là admin/creator."""
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        return True
    try:
        m = await context.bot.get_chat_member(chat.id, user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        # vẫn trả False nhưng handler sẽ trả lời rõ ràng
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
        minutes = max(10, minutes)  # min 10p cho an toàn
        ps = _get_ps(db, update.effective_chat.id)
        ps.interval_minutes = minutes
        ps.last_sent_at = None  # ép tick kế tiếp đủ điều kiện sẽ gửi
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
        # ====== NGÔN NGỮ / LANGUAGE SWITCH ======
from core.lang import t, LANG
USER_LANG: dict[int, str] = {}  # user_id -> 'vi' | 'en'

USER_LANG = {}  # Lưu ngôn ngữ từng user

async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /lang <mã_ngôn_ngữ> — ví dụ: /lang en hoặc /lang vi"""
    if not context.args:
        return await update.message.reply_text(
            "🌐 Cú pháp: /lang <vi|en>\nVí dụ: /lang en"
        )
    code = context.args[0].lower()
    if code not in LANG:
        return await update.message.reply_text("❗ Ngôn ngữ không hợp lệ. Dùng vi hoặc en.")
    USER_LANG[update.effective_user.id] = code
    await update.message.reply_text(
        "✅ Ngôn ngữ đã được đổi sang " + ("🇻🇳 Tiếng Việt" if code == "vi" else "🇬🇧 English")
    )
# ====== END FILTERS & TOGGLES BLOCK ======



if __name__ == "__main__":
    main()
