import secrets
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from core.models import SessionLocal, User, LicenseKey, Trial, Whitelist, add_days, now_utc

HELP_PRO = (
    "<b>Gói PRO</b>\n"
    "• Dùng thử 7 ngày: /trial\n"
    "• Nhập key: /redeem &lt;key&gt;\n"
    "• Tạo key (OWNER): /genkey &lt;days&gt;\n"
    "• Whitelist link: /wl_add &lt;domain&gt; | /wl_del &lt;domain&gt; | /wl_list\n"
)

async def pro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(update.effective_chat.id, HELP_PRO, parse_mode=ParseMode.HTML)

async def ensure_user(user_id: int, username: str | None):
    db = SessionLocal()
    u = db.get(User, user_id)
    if not u:
        u = User(id=user_id, username=username or "")
        db.add(u)
        db.commit()
    return u

async def trial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db = SessionLocal()
    user = await ensure_user(u.id, u.username)

    ex = db.query(Trial).filter_by(user_id=u.id, active=True).one_or_none()
    if ex:
        return await update.message.reply_text("❗ Bạn đã kích hoạt trial trước đó.")

    trial = Trial(user_id=u.id, started_at=now_utc(), expires_at=add_days(7), active=True)
    user.is_pro = True
    user.pro_expires_at = trial.expires_at
    db.add(trial)
    db.commit()
    await update.message.reply_text("✅ Đã kích hoạt dùng thử 7 ngày!")

async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /redeem <key>")

    key = context.args[0].strip()
    db = SessionLocal()
    lk = db.query(LicenseKey).filter_by(key=key).one_or_none()
    if not lk or lk.used:
        return await update.message.reply_text("❌ Key không hợp lệ hoặc đã dùng.")

    u = update.effective_user
    user = await ensure_user(u.id, u.username)

    user.is_pro = True
    user.pro_expires_at = add_days(lk.days)
    lk.used = True
    lk.issued_to = u.id
    db.commit()
    await update.message.reply_text(f"✅ Kích hoạt PRO trong {lk.days} ngày.")

async def genkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int):
    if update.effective_user.id != owner_id:
        return await update.message.reply_text("❌ Bạn không có quyền dùng lệnh này.")

    days = 30
    if context.args:
        try:
            days = max(1, int(context.args[0]))
        except ValueError:
            return await update.message.reply_text("Cú pháp: /genkey <days>")

    key = "PRO-" + secrets.token_urlsafe(12)
    db = SessionLocal()
    lk = LicenseKey(key=key, days=days)
    db.add(lk); db.commit()

    await update.message.reply_text(f"🔑 Key mới: <code>{key}</code> ({days} ngày)", parse_mode=ParseMode.HTML)

# Whitelist commands
async def wl_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /wl_add <domain>")
    domain = context.args[0].lower()
    db = SessionLocal()
    ex = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
    if ex:
        return await update.message.reply_text("Đã có trong whitelist.")
    it = Whitelist(chat_id=update.effective_chat.id, domain=domain)
    db.add(it); db.commit()
    await update.message.reply_text(f"✅ Đã thêm: {domain}")

async def wl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /wl_del <domain>")
    domain = context.args[0].lower()
    db = SessionLocal()
    it = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
    if not it:
        return await update.message.reply_text("Không thấy domain này.")
    db.delete(it); db.commit()
    await update.message.reply_text(f"🗑️ Đã xoá: {domain}")

async def wl_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    items = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id).all()
    if not items:
        return await update.message.reply_text("Danh sách whitelist trống.")
    out = "\n".join(f"• {i.domain}" for i in items)
    await update.message.reply_text(out)

def register_handlers(app: Application, owner_id: int | None = None):
    # PRO menu
    app.add_handler(CommandHandler("pro", pro_cmd))
    app.add_handler(CommandHandler("trial", trial_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    # owner genkey
    app.add_handler(CommandHandler("genkey", lambda u, c: genkey_cmd(u, c, owner_id or 0)))
    # whitelist
    app.add_handler(CommandHandler("wl_add", wl_add))
    app.add_handler(CommandHandler("wl_del", wl_del))
    app.add_handler(CommandHandler("wl_list", wl_list))
