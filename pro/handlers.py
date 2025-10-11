# pro/handlers.py
from __future__ import annotations

import secrets
from datetime import timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from core.models import (
    SessionLocal,
    User,
    LicenseKey,
    Trial,
    Whitelist,
    PromoSetting,   # cần có model này: chat_id, enabled(bool), text(str), interval_min(int, default=60), last_sent_at(DateTime|null)
    add_days,
    now_utc,
)

HELP_PRO = (
    "<b>Gói PRO</b>\n"
    "• Dùng thử 7 ngày: /trial\n"
    "• Nhập key: /redeem &lt;key&gt;\n"
    "• Tạo key (OWNER): /genkey &lt;days&gt;\n"
    "• Whitelist: /wl_add &lt;domain&gt; | /wl_del &lt;domain&gt; | /wl_list\n"
    "• Quảng cáo tự động nhóm: /ad_on, /ad_off, /ad_set &lt;text&gt;, /ad_interval &lt;phút&gt;\n"
)

# ------------------------ Helpers ------------------------

async def pro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_PRO, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

def _is_owner(owner_id: int | None, user_id: int) -> bool:
    try:
        return bool(owner_id) and int(owner_id) == int(user_id)
    except Exception:
        return False

async def _admin_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Kiểm tra admin nhóm."""
    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        m = await context.bot.get_chat_member(chat_id, user_id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

def _ensure_user(db: SessionLocal, user_id: int, username: str | None) -> User:
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if not u:
        u = User(id=user_id, username=username or "")
        db.add(u)
        db.flush()
    return u

# ------------------------ PRO core ------------------------

async def trial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db = SessionLocal()
    try:
        user = _ensure_user(db, u.id, u.username)

        # đang PRO còn hạn -> báo lại
        if user.is_pro and user.pro_expires_at and user.pro_expires_at > now_utc():
            remain = user.pro_expires_at - now_utc()
            days = max(0, remain.days)
            return await update.message.reply_text(f"✅ Bạn đang là PRO. Còn ~ {days} ngày.")

        # đã từng trial & kết thúc -> không cho lại
        t = db.query(Trial).filter_by(user_id=u.id).one_or_none()
        if t and not t.active:
            return await update.message.reply_text("❗ Bạn đã dùng thử trước đó.")

        # cấp trial 7 ngày
        if not t:
            t = Trial(user_id=u.id, started_at=now_utc(), expires_at=add_days(7), active=True)
            db.add(t)
        else:
            t.started_at = now_utc()
            t.expires_at = add_days(7)
            t.active = True

        user.is_pro = True
        user.pro_expires_at = t.expires_at
        db.commit()
        await update.message.reply_text("✅ Đã kích hoạt dùng thử 7 ngày!")
    finally:
        db.close()

async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: <code>/redeem KEY-XXXXX</code>", parse_mode=ParseMode.HTML)

    key = context.args[0].strip()
    db = SessionLocal()
    try:
        lk = db.query(LicenseKey).filter_by(key=key).one_or_none()
        if not lk or lk.used:
            return await update.message.reply_text("❌ Key không hợp lệ hoặc đã dùng.")

        u = update.effective_user
        user = _ensure_user(db, u.id, u.username)

        days = lk.days or 30
        user.is_pro = True
        user.pro_expires_at = now_utc() + timedelta(days=days)
        lk.used = True
        lk.issued_to = u.id
        db.commit()
        await update.message.reply_text(f"✅ Kích hoạt PRO {days} ngày thành công!")
    finally:
        db.close()

async def genkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int = 0):
    if not _is_owner(owner_id, update.effective_user.id):
        return await update.message.reply_text("❌ Bạn không có quyền dùng lệnh này.")
    days = 30
    if context.args:
        try:
            days = max(1, int(context.args[0]))
        except Exception:
            return await update.message.reply_text("Cú pháp: <code>/genkey &lt;days&gt;</code>", parse_mode=ParseMode.HTML)

    code = "PRO-" + secrets.token_urlsafe(12).upper()
    db = SessionLocal()
    try:
        lk = LicenseKey(key=code, days=days)
        db.add(lk)
        db.commit()
        await update.message.reply_text(
            f"🔑 Key mới ({days} ngày): <code>{code}</code>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    finally:
        db.close()

# ------------------------ Whitelist ------------------------

async def wl_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _admin_only(update, context):
        return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
    if not context.args:
        return await update.message.reply_text("Cú pháp: <code>/wl_add domain.com</code>", parse_mode=ParseMode.HTML)
    domain = context.args[0].lower()

    db = SessionLocal()
    try:
        ex = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
        if ex:
            return await update.message.reply_text("Đã có trong whitelist.")
        db.add(Whitelist(chat_id=update.effective_chat.id, domain=domain))
        db.commit()
        await update.message.reply_text(f"✅ Đã thêm: {domain}")
    finally:
        db.close()

async def wl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _admin_only(update, context):
        return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
    if not context.args:
        return await update.message.reply_text("Cú pháp: <code>/wl_del domain.com</code>", parse_mode=ParseMode.HTML)
    domain = context.args[0].lower()

    db = SessionLocal()
    try:
        it = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
        if not it:
            return await update.message.reply_text("Không thấy domain này.")
        db.delete(it)
        db.commit()
        await update.message.reply_text(f"🗑️ Đã xoá: {domain}")
    finally:
        db.close()

async def wl_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        items = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id).all()
        if not items:
            return await update.message.reply_text("Danh sách whitelist trống.")
        out = "\n".join(f"• {i.domain}" for i in items)
        await update.message.reply_text(out, disable_web_page_preview=True)
    finally:
        db.close()

# ------------------------ Quảng cáo tự động ------------------------

async def ad_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _admin_only(update, context):
        return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
    db = SessionLocal()
    try:
        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, enabled=True)
            db.add(s)
        else:
            s.enabled = True
        db.commit()
        await update.message.reply_text("✅ Đã bật quảng cáo tự động cho nhóm này.")
    finally:
        db.close()

async def ad_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _admin_only(update, context):
        return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
    db = SessionLocal()
    try:
        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, enabled=False)
            db.add(s)
        else:
            s.enabled = False
        db.commit()
        await update.message.reply_text("⛔️ Đã tắt quảng cáo tự động cho nhóm này.")
    finally:
        db.close()

async def ad_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _admin_only(update, context):
        return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
    text = " ".join(context.args).strip()
    if not text:
        return await update.message.reply_text("Cú pháp: <code>/ad_set &lt;nội dung&gt;</code>", parse_mode=ParseMode.HTML)

    db = SessionLocal()
    try:
        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, enabled=True, text=text)
            db.add(s)
        else:
            s.text = text
        db.commit()
        await update.message.reply_text("📝 Đã cập nhật nội dung quảng cáo.")
    finally:
        db.close()

async def ad_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _admin_only(update, context):
        return await update.message.reply_text("Chỉ admin mới dùng lệnh này.")
    if not context.args:
        return await update.message.reply_text("Cú pháp: <code>/ad_interval &lt;phút&gt;</code>", parse_mode=ParseMode.HTML)
    try:
        minutes = max(10, int(context.args[0]))
    except Exception:
        return await update.message.reply_text("Giá trị không hợp lệ.")

    db = SessionLocal()
    try:
        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, enabled=True, interval_min=minutes)
            db.add(s)
        else:
            s.interval_min = minutes
        db.commit()
        await update.message.reply_text(f"⏱ Chu kỳ quảng cáo: {minutes} phút.")
    finally:
        db.close()

# job chạy mỗi 60s, gửi QC cho nhóm đã đến hạn
async def _promo_tick(context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    now = now_utc()
    try:
        enabled = db.query(PromoSetting).filter_by(enabled=True).all()
        for s in enabled:
            if not s.text:
                continue
            interval = (s.interval_min or 60) * 60
            last = s.last_sent_at or (now - timedelta(days=365))
            if (now - last).total_seconds() >= interval:
                try:
                    await context.bot.send_message(s.chat_id, s.text, disable_web_page_preview=True)
                    s.last_sent_at = now
                    db.commit()
                except Exception:
                    # không phá vòng lặp nếu 1 nhóm lỗi
                    db.rollback()
                    continue
    finally:
        db.close()

# ------------------------ Register ------------------------

def register_handlers(app: Application, owner_id: int | None = None):
    # menu & PRO
    app.add_handler(CommandHandler("pro", pro_cmd))
    app.add_handler(CommandHandler("trial", trial_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("genkey", lambda u, c: genkey_cmd(u, c, owner_id or 0)))

    # whitelist (admin)
    app.add_handler(CommandHandler("wl_add", wl_add))
    app.add_handler(CommandHandler("wl_del", wl_del))
    app.add_handler(CommandHandler("wl_list", wl_list))

    # quảng cáo tự động (admin)
    app.add_handler(CommandHandler("ad_on", ad_on))
    app.add_handler(CommandHandler("ad_off", ad_off))
    app.add_handler(CommandHandler("ad_set", ad_set))
    app.add_handler(CommandHandler("ad_interval", ad_interval))

    # job queue: check mỗi 60 giây
    if app.job_queue and not app.bot_data.get("promo_job_installed"):
        app.job_queue.run_repeating(_promo_tick, interval=60, name="promo_tick", first=10)
        app.bot_data["promo_job_installed"] = True
        print("[pro] promo_tick job installed")
