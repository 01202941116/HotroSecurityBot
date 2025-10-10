# pro/handlers.py
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from core.models import SessionLocal, User, Trial, LicenseKey

# ===== /pro: hiển thị hướng dẫn PRO =====
async def pro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Gói PRO: dùng thử 7 ngày với /trial, hoặc nhập key bằng /redeem <key>.\n"
        "• /trial – kích hoạt dùng thử 7 ngày (1 lần/người)\n"
        "• /redeem <key> – kích hoạt PRO bằng license key\n"
    )
    await update.message.reply_text(text)

# ===== /trial: kích hoạt dùng thử 7 ngày =====
async def trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = SessionLocal()

    # nếu chưa có record user thì tạo
    u = db.query(User).filter_by(id=user.id).one_or_none()
    if not u:
        u = User(id=user.id, username=user.username or None, is_pro=False)
        db.add(u)
        db.commit()

    # đã từng dùng thử?
    existed = db.query(Trial).filter_by(user_id=user.id).one_or_none()
    if existed:
        return await update.message.reply_text("⚠️ Bạn đã dùng thử trước đó, không thể kích hoạt lại.")

    # tạo trial 7 ngày
    now = datetime.utcnow()
    expires = now + timedelta(days=7)

    t = Trial(user_id=user.id, started_at=now, expires_at=expires, active=True)
    db.add(t)

    # bật PRO cho user tới ngày hết hạn
    u.is_pro = True
    u.pro_expires_at = expires
    db.commit()

    await update.message.reply_text(
        f"✅ Đã kích hoạt PRO dùng thử 7 ngày cho @{user.username or user.id}.\n"
        f"Hết hạn: {expires.strftime('%d/%m/%Y %H:%M:%S UTC')}"
    )

# ===== /redeem <key>: kích hoạt key PRO =====
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /redeem <key>")

    key_input = context.args[0].strip()
    db = SessionLocal()

    lk = db.query(LicenseKey).filter_by(key=key_input).one_or_none()
    if not lk:
        return await update.message.reply_text("❌ Key không hợp lệ.")

    if lk.used:
        return await update.message.reply_text("❌ Key đã được sử dụng.")

    # tạo (hoặc cập nhật) user
    tg_user = update.effective_user
    u = db.query(User).filter_by(id=tg_user.id).one_or_none()
    if not u:
        u = User(id=tg_user.id, username=tg_user.username or None)
        db.add(u)
        db.commit()

    # tính hạn theo 'days' của key
    now = datetime.utcnow()
    base = u.pro_expires_at if (u.pro_expires_at and u.pro_expires_at > now) else now
    new_expires = base + timedelta(days=lk.days or 30)

    u.is_pro = True
    u.pro_expires_at = new_expires

    lk.used = True
    lk.issued_to = u.id
    db.commit()

    await update.message.reply_text(
        f"✅ Kích hoạt key thành công!\n"
        f"Hạn PRO mới: {new_expires.strftime('%d/%m/%Y %H:%M:%S UTC')}"
    )

# ===== đăng ký vào Application =====
def register_handlers(app):
    app.add_handler(CommandHandler("pro", pro_menu))
    app.add_handler(CommandHandler("trial", trial))
    app.add_handler(CommandHandler("redeem", redeem))
