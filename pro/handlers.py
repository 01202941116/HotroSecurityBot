# pro/handlers.py
from telegram.ext import CommandHandler, ContextTypes
from telegram import Update
import secrets
from datetime import datetime, timedelta
from core.models import SessionLocal, LicenseKey, User, Trial

def register_handlers(app, owner_id=None):
    # /genkey <days> – chỉ OWNER dùng
    async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if owner_id and update.effective_user.id != owner_id:
            await update.message.reply_text("Bạn không có quyền dùng lệnh này.")
            return
        if not context.args:
            await update.message.reply_text("Cú pháp: /genkey <days>")
            return
        try:
            days = max(1, int(context.args[0]))
        except ValueError:
            await update.message.reply_text("Số ngày không hợp lệ.")
            return

        key = "PRO-" + secrets.token_urlsafe(12)
        db = SessionLocal()
        lic = LicenseKey(key=key, days=days)
        db.add(lic); db.commit()
        await update.message.reply_text(f"✅ Key: <code>{key}</code> (hạn {days} ngày)", parse_mode="HTML")

    # /redeem <key>
    async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Cú pháp: /redeem <key>")
            return
        key = context.args[0].strip()
        db = SessionLocal()
        lic = db.query(LicenseKey).filter_by(key=key, used=False).one_or_none()
        if not lic:
            await update.message.reply_text("Key không hợp lệ hoặc đã dùng.")
            return
        u = db.query(User).get(update.effective_user.id) or User(id=update.effective_user.id, username=update.effective_user.username)
        u.is_pro = True
        u.pro_expires_at = (datetime.utcnow() + timedelta(days=lic.days))
        lic.used = True
        lic.issued_to = u.id
        db.add(u); db.commit()
        await update.message.reply_text(f"✅ Kích hoạt PRO thành công. Hạn tới: {u.pro_expires_at:%Y-%m-%d %H:%M:%S} UTC")

    # /trial – kích hoạt dùng thử (1 lần/người)
    async def trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
        db = SessionLocal()
        u = db.query(User).get(update.effective_user.id) or User(id=update.effective_user.id, username=update.effective_user.username)
        t = db.query(Trial).filter_by(user_id=u.id, active=True).one_or_none()
        if t:
            await update.message.reply_text("Bạn đã dùng thử rồi.")
            return
        u.is_pro = True
        u.pro_expires_at = datetime.utcnow() + timedelta(days=7)
        db.add(Trial(user_id=u.id, started_at=datetime.utcnow(), expires_at=u.pro_expires_at, active=True))
        db.add(u); db.commit()
        await update.message.reply_text("✅ Đã kích hoạt dùng thử 7 ngày.")

    app.add_handler(CommandHandler("genkey", genkey))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("trial", trial))
