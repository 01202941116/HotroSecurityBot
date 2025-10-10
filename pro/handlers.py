from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from core.models import SessionLocal, License

# ===== DÙNG THỬ 7 NGÀY =====
async def trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = SessionLocal()

    # kiểm tra nếu đã kích hoạt key dùng thử trước đó
    old = db.query(License).filter_by(user_id=user_id, key_type="trial").one_or_none()
    if old:
        return await update.message.reply_text("⚠️ Bạn đã từng dùng thử miễn phí trước đó, không thể kích hoạt lại.")

    # tạo key mới dùng thử 7 ngày
    expires = datetime.utcnow() + timedelta(days=7)
    trial_key = f"trial-{user_id}-{int(datetime.utcnow().timestamp())}"

    lic = License(
        user_id=user_id,
        key=trial_key,
        key_type="trial",
        expires=expires,
        activated=True,
    )
    db.add(lic)
    db.commit()

    await update.message.reply_text(
        f"✅ Gói PRO dùng thử đã được kích hoạt!\nHiệu lực đến: {expires.strftime('%d/%m/%Y %H:%M:%S UTC')}\n"
        "Cảm ơn bạn đã trải nghiệm HotroSecurityBot 💙"
    )
