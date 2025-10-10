
import os, re, random
from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.models import SessionLocal, init_db, Setting, Filter, Whitelist, Captcha
from .license_manager import generate_key, redeem_key, start_trial
from .decorators import pro_only

OWNER_ID = int(os.getenv("OWNER_ID","0"))
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME","")

CAPTCHA_TIMEOUT = 120  # seconds

def register_handlers(app):
    init_db()
    app.bot_data["CONTACT_USERNAME"] = CONTACT_USERNAME

    async def pro_panel(update, context):
        kb = [[
            InlineKeyboardButton("🔑 Nhập KEY", callback_data="pro_redeem"),
            InlineKeyboardButton("🎁 Dùng thử 7 ngày", callback_data="pro_trial"),
        ],[ InlineKeyboardButton("💬 Liên hệ tạo KEY", url=f"https://t.me/{CONTACT_USERNAME}" if CONTACT_USERNAME else "https://t.me") ]]
        await update.message.reply_text("<b>Gói PRO</b> – mở tính năng nâng cao.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    async def cbq(update, context):
        q = update.callback_query
        if q.data == "pro_trial":
            ok, msg = start_trial(q.from_user.id, q.from_user.username)
            await q.answer(); await q.message.reply_text(("✅ " if ok else "⚠️ ") + msg)
        elif q.data == "pro_redeem":
            await q.answer()
            await q.message.reply_text("Gửi KEY theo cú pháp:\n<code>/redeem ABCDEF-XXXXXX-YYYYYY-ZZZZZZ</code>", parse_mode="HTML")

    app.add_handler(CommandHandler("pro", pro_panel))
    app.add_handler(CallbackQueryHandler(cbq, pattern=r"^pro_"))

    async def redeem_cmd(update, context):
        if len(context.args) != 1:
            return await update.message.reply_text("Cú pháp: <code>/redeem KEY</code>", parse_mode="HTML")
        ok, msg = redeem_key(update.effective_user.id, update.effective_user.username, context.args[0].strip())
        await update.message.reply_text(("✅ " if ok else "⚠️ ") + msg)

    async def genkey(update, context):
        if update.effective_user.id != OWNER_ID: return
        days = int(context.args[0]) if context.args else 30
        k = generate_key(days=days, tier="pro")
        await update.message.reply_text(f"🔑 Key ({days} ngày): <code>{k}</code>", parse_mode="HTML")

    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("genkey", genkey))

    # Whitelist (PRO)
    @pro_only
    async def wl_add(update, context):
        if not context.args: return await update.message.reply_text("Cú pháp: /wl_add <domain>")
        domain = context.args[0].lower().strip()
        db = SessionLocal(); db.add(Whitelist(chat_id=update.effective_chat.id, domain=domain)); db.commit()
        await update.message.reply_text(f"✅ Đã thêm whitelist: {domain}")

    @pro_only
    async def wl_del(update, context):
        if not context.args: return await update.message.reply_text("Cú pháp: /wl_del <domain>")
        domain = context.args[0].lower().strip()
        db = SessionLocal(); it = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
        if not it: return await update.message.reply_text("Không tìm thấy.")
        db.delete(it); db.commit(); await update.message.reply_text("🗑️ Đã xoá whitelist.")

    @pro_only
    async def wl_list(update, context):
        db = SessionLocal(); items = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id).all()
        if not items: return await update.message.reply_text("Trống.")
        await update.message.reply_text("\n".join(f"- {i.domain}" for i in items))

    app.add_handler(CommandHandler("wl_add", wl_add))
    app.add_handler(CommandHandler("wl_del", wl_del))
    app.add_handler(CommandHandler("wl_list", wl_list))

    # Captcha on join (PRO)
    @pro_only
    async def captcha_on(update, context):
        context.bot_data.setdefault("captcha_chats", set()).add(update.effective_chat.id)
        await update.message.reply_text("✅ Đã bật Captcha khi thành viên mới vào.")

    @pro_only
    async def captcha_off(update, context):
        context.bot_data.setdefault("captcha_chats", set()).discard(update.effective_chat.id)
        await update.message.reply_text("❎ Đã tắt Captcha.")

    app.add_handler(CommandHandler("captcha_on", captcha_on))
    app.add_handler(CommandHandler("captcha_off", captcha_off))

    async def on_new_member(update, context):
        chat_id = update.effective_chat.id
        if chat_id not in context.bot_data.get("captcha_chats", set()): return
        import random
        for m in update.message.new_chat_members:
            a = random.randint(2,9); b = random.randint(2,9); ans = str(a+b)
            from core.models import Captcha, SessionLocal
            db = SessionLocal(); db.add(Captcha(chat_id=chat_id, user_id=m.id, answer=ans)); db.commit()
            await update.effective_chat.send_message(f"👋 Chào {m.mention_html()}! Trả lời trong 120s: <b>{a} + {b} = ?</b>", parse_mode="HTML")

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))

    async def on_captcha_answer(update, context):
        text = (update.message.text or "").strip()
        if not text.isdigit(): return
        from core.models import Captcha, SessionLocal
        db = SessionLocal(); it = db.query(Captcha).filter_by(chat_id=update.effective_chat.id, user_id=update.effective_user.id).one_or_none()
        if not it: return
        if it.answer == text:
            db.delete(it); db.commit(); await update.message.reply_text("✅ Xác minh thành công!")
        else:
            await update.message.reply_text("❌ Sai, thử lại.")

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_captcha_answer))
