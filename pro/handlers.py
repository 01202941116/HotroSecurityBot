from telegram.ext import CommandHandler, ContextTypes
from telegram import Update

async def pro_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = context.bot_data.get("contact") or "admin"
    await update.message.reply_text(
        f"Gói PRO: dùng thử 7 ngày (/trial) hoặc nhập key /redeem <key>\nLiên hệ @{contact} để mua key."
    )

def register_handlers(app):
    # Không truy cập app.bot trước khi bot được khởi tạo
    app.add_handler(CommandHandler("pro", pro_panel))
