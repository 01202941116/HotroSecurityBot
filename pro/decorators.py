
from functools import wraps
from datetime import datetime
from .models import SessionLocal, User
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def pro_only(handler):
    @wraps(handler)
    async def wrapper(update, context):
        user_id = update.effective_user.id
        db = SessionLocal()
        u = db.get(User, user_id)
        now = datetime.utcnow()
        if not u or not u.is_pro or not u.pro_expires_at or u.pro_expires_at < now:
            btns = [[
                InlineKeyboardButton("Dùng thử 7 ngày", callback_data="pro_trial"),
                InlineKeyboardButton("Liên hệ mua KEY", url=f"https://t.me/{context.bot_data.get('CONTACT_USERNAME','')}")
            ]]
            await update.effective_chat.send_message(
                "⛔ Tính năng chỉ dành cho <b>PRO</b>.",
                reply_markup=InlineKeyboardMarkup(btns), parse_mode="HTML"
            )
            return
        return await handler(update, context)
    return wrapper
