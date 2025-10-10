# pro/handlers.py
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

# Đăng ký toàn bộ handler vào app
def register_handlers(app):
    app.add_handler(CommandHandler("pro", pro_panel))
    app.add_handler(CommandHandler("trial", trial_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("genkey", genkey_cmd))  # owner only

    app.add_handler(CommandHandler("wl_add", wl_add))
    app.add_handler(CommandHandler("wl_del", wl_del))
    app.add_handler(CommandHandler("wl_list", wl_list))

    app.add_handler(CommandHandler("captcha_on", captcha_on))
    app.add_handler(CommandHandler("captcha_off", captcha_off))

# ===== Utils =====
def _owner_only(user_id: int) -> bool:
    import os
    try:
        owner = int(os.getenv("OWNER_ID", "0"))
    except Exception:
        owner = 0
    return owner != 0 and user_id == owner

async def pro_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Gói PRO: dùng thử 7 ngày với /trial hoặc nhập key bằng /redeem <key>\n"
        "Liên hệ hỗ trợ: @" + (context.application.bot_data.get("contact") or "HotroSecurity_Bot")
    )
    await update.message.reply_text(txt)

async def trial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core.models import SessionLocal, Trial, User
    user = update.effective_user
    db = SessionLocal()
    try:
        # đảm bảo có user row
        u = db.get(User, user.id) or User(id=user.id, username=user.username)
        db.add(u)
        db.commit()

        t = db.query(Trial).filter_by(user_id=user.id, active=True).one_or_none()
        if t:
            return await update.message.reply_text("Bạn đã kích hoạt dùng thử trước đó.")

        expires = datetime.utcnow() + timedelta(days=7)
        t = Trial(user_id=user.id, started_at=datetime.utcnow(), expires_at=expires, active=True)
        db.add(t)

        u.is_pro = True
        u.pro_expires_at = expires
        db.commit()
        await update.message.reply_text("Đã kích hoạt PRO dùng thử 7 ngày. Hạn: " + expires.strftime("%Y-%m-%d %H:%M UTC"))
    finally:
        db.close()

async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /redeem <key>")
    key = context.args[0]

    from core.models import SessionLocal, LicenseKey, User
    user = update.effective_user
    db = SessionLocal()
    try:
        lic = db.query(LicenseKey).filter_by(key=key, used=False).one_or_none()
        if not lic:
            return await update.message.reply_text("Key không hợp lệ hoặc đã dùng.")

        u = db.get(User, user.id) or User(id=user.id, username=user.username)
        db.add(u)

        # kích hoạt
        u.is_pro = True
        u.pro_expires_at = datetime.utcnow() + timedelta(days=lic.days)
        lic.used = True
        lic.issued_to = user.id

        db.commit()
        await update.message.reply_text(f"Đã kích hoạt PRO {lic.days} ngày. Hạn: {u.pro_expires_at:%Y-%m-%d %H:%M UTC}")
    finally:
        db.close()

async def genkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Owner-only
    if not _owner_only(update.effective_user.id):
        return await update.message.reply_text("Bạn không có quyền.")
    if not context.args:
        return await update.message.reply_text("Cú pháp: /genkey <days> (VD: /genkey 30)")

    try:
        days = int(context.args[0])
        if days <= 0:
            raise ValueError
    except Exception:
        return await update.message.reply_text("Số ngày không hợp lệ.")

    import secrets
    from core.models import SessionLocal, LicenseKey
    key = "KEY-" + secrets.token_urlsafe(16)

    db = SessionLocal()
    try:
        db.add(LicenseKey(key=key, days=days))
        db.commit()
        await update.message.reply_text(f"Đã tạo key: <code>{key}</code> ({days} ngày)", parse_mode="HTML")
    finally:
        db.close()

# ===== Whitelist link =====
async def wl_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /wl_add <domain>")
    domain = context.args[0].lower().strip()
    from core.models import SessionLocal, Whitelist
    db = SessionLocal()
    try:
        if not db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none():
            db.add(Whitelist(chat_id=update.effective_chat.id, domain=domain))
            db.commit()
        await update.message.reply_text(f"✅ Đã thêm whitelist: {domain}")
    finally:
        db.close()

async def wl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /wl_del <domain>")
    domain = context.args[0].lower().strip()
    from core.models import SessionLocal, Whitelist
    db = SessionLocal()
    try:
        it = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
        if not it:
            return await update.message.reply_text("Không tìm thấy domain.")
        db.delete(it)
        db.commit()
        await update.message.reply_text(f"🗑️ Đã xoá: {domain}")
    finally:
        db.close()

async def wl_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core.models import SessionLocal, Whitelist
    db = SessionLocal()
    try:
        items = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id).all()
        if not items:
            return await update.message.reply_text("Danh sách whitelist trống.")
        out = "\n".join(f"• {w.domain}" for w in items)
        await update.message.reply_text(out)
    finally:
        db.close()

# ===== Captcha flags (placeholder bật/tắt) =====
async def captcha_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core.models import SessionLocal, Setting
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            from core.models import Setting as S
            s = S(chat_id=update.effective_chat.id)
            db.add(s)
        # Ở đây chỉ set cờ, phần xử lý captcha join có thể bổ sung sau
        # (để không crash khi gọi lệnh)
        db.commit()
        await update.message.reply_text("✅ Captcha: ON (placeholder)")
    finally:
        db.close()

async def captcha_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core.models import SessionLocal, Setting
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            from core.models import Setting as S
            s = S(chat_id=update.effective_chat.id)
            db.add(s)
        db.commit()
        await update.message.reply_text("❎ Captcha: OFF (placeholder)")
    finally:
        db.close()
