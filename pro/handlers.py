
from telegram.ext import CommandHandler, ContextTypes
from telegram import Update

async def pro_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = context.bot_data.get("contact") or "admin"
    await update.message.reply_text(
        "Gói PRO: dùng thử 7 ngày (/trial) hoặc nhập key /redeem <key>\nLiên hệ @%s để mua key." % contact
    )

def register_handlers(app):
    app.bot_data["contact"] = app.bot.username
    app.add_handler(CommandHandler("pro", pro_panel))
