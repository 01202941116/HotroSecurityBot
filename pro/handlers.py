
import os
from telegram.ext import CommandHandler, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .models import init_db
from .license_manager import generate_key, redeem_key, start_trial
from .decorators import pro_only

OWNER_ID = int(os.getenv("OWNER_ID","0"))
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME","Myyduyenng")

def register_handlers(app):
    app.bot_data["CONTACT_USERNAME"] = CONTACT_USERNAME
    init_db()

    async def pro_panel(update, context):
        kb = [[
            InlineKeyboardButton("🔑 Nhập KEY", callback_data="pro_redeem"),
            InlineKeyboardButton("🎁 Dùng thử 7 ngày", callback_data="pro_trial"),
        ],[ InlineKeyboardButton("💬 Liên hệ tạo KEY", url=f"https://t.me/{CONTACT_USERNAME}") ]]
        await update.message.reply_text(
            "<b>Gói PRO</b> – mở khoá tính năng nâng cao.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
        )

    async def cbq(update, context):
        q = update.callback_query
        data = q.data
        if data == "pro_trial":
            ok, msg = start_trial(q.from_user.id, q.from_user.username)
            await q.answer()
            await q.message.reply_text(("✅ " if ok else "⚠️ ") + msg)
        elif data == "pro_redeem":
            await q.answer()
            await q.message.reply_text("Gửi KEY theo cú pháp:\n<code>/redeem ABCDEF-XXXXXX-YYYYYY-ZZZZZZ</code>", parse_mode="HTML")

    async def redeem(update, context):
        if len(context.args) != 1:
            return await update.message.reply_text("Cú pháp: <code>/redeem KEY</code>", parse_mode="HTML")
        ok, msg = redeem_key(update.effective_user.id, update.effective_user.username, context.args[0].strip())
        await update.message.reply_text(("✅ " if ok else "⚠️ ") + msg)

    async def genkey(update, context):
        if update.effective_user.id != OWNER_ID:
            return
        days = int(context.args[0]) if context.args else int(os.getenv("PRO_DEFAULT_DAYS","30"))
        key = generate_key(days=days, tier="pro")
        await update.message.reply_text(f"🔑 Key ({days} ngày): <code>{key}</code>", parse_mode="HTML")

    @pro_only
    async def antiraid_on(update, context):
        await update.message.reply_text("✅ Anti-raid PRO đã bật.")

    app.add_handler(CommandHandler("pro", pro_panel))
    app.add_handler(CallbackQueryHandler(cbq, pattern=r"^pro_"))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("genkey", genkey))
    app.add_handler(CommandHandler("antiraid_pro_on", antiraid_on))
