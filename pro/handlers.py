# pro/handlers.py
from __future__ import annotations

from core.lang import t  # i18n

import secrets
from datetime import timedelta, timezone as _tz

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from core.models import (
    SessionLocal,
    User,
    LicenseKey,
    Trial,
    Whitelist,
    PromoSetting,
    add_days,
    now_utc,
)

# ====== i18n: lưu lựa chọn ngôn ngữ tạm thời trong RAM (đơn giản) ======
USER_LANG: dict[int, str] = {}  # user_id -> "vi" | "en"

def _lang(update: Update) -> str:
    uid = update.effective_user.id if update.effective_user else 0
    return USER_LANG.get(uid, "vi")

# ---------- Safe reply helper ----------
async def _reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kw):
    """
    Gửi reply an toàn cho mọi loại update:
    - ưu tiên reply vào effective_message nếu có
    - nếu không có, gửi thẳng vào effective_chat
    """
    m = update.effective_message
    if m:
        return await m.reply_text(text, **kw)
    chat = update.effective_chat
    if chat:
        return await context.bot.send_message(chat.id, text, **kw)
    # không có nơi để gửi -> bỏ qua
    return None

async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        cur = USER_LANG.get(uid, "vi").upper()
        return await _reply(
            update, context,
            f"Ngôn ngữ hiện tại / Current language: {cur}\nDùng/Use: /lang vi | /lang en"
        )
    v = context.args[0].lower()
    if v not in ("vi", "en"):
        return await _reply(
            update, context,
            "Ngôn ngữ không hợp lệ. Dùng: /lang vi | /lang en\nInvalid language. Use: /lang vi | /lang en"
        )
    USER_LANG[uid] = v
    return await _reply(update, context, f"✅ Đã đổi ngôn ngữ sang / Switched to: {v.upper()}")

# ====== Timezone-safe helpers ======
def ensure_aware(dt):
    """Trả về datetime timezone-aware (UTC). Nếu dt naive -> gán tzinfo=UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_tz.utc)

def now_aw():
    """Thời gian hiện tại UTC (timezone-aware)."""
    # now_utc() có thể trả về naive -> chuẩn hoá
    return ensure_aware(now_utc())

def _has_active_pro(db: SessionLocal, user_id: int) -> bool:
    """User còn PRO/TRIAL? (timezone-aware)."""
    now = now_aw()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u and u.is_pro:
        exp = ensure_aware(u.pro_expires_at)
        if exp and exp > now:
            return True
    t_trial = db.query(Trial).filter_by(user_id=user_id, active=True).one_or_none()
    if t_trial:
        exp = ensure_aware(t_trial.expires_at)
        if exp and exp > now:
            return True
    return False

HELP_PRO_VI = (
    "<b>Gói PRO</b>\n"
    "• Dùng thử 7 ngày: /trial\n"
    "• Nhập key: /redeem &lt;key&gt;\n"
    "• Tạo key (OWNER): /genkey &lt;days&gt;\n"
    "• Whitelist: /wl_add &lt;domain&gt; | /wl_del &lt;domain&gt; | /wl_list\n"
    "• Quảng cáo tự động nhóm: /ad_on, /ad_off, /ad_set &lt;text&gt;, /ad_interval &lt;phút&gt;\n"
    "• Đổi ngôn ngữ: /lang vi hoặc /lang en\n"
)

HELP_PRO_EN = (
    "<b>PRO Package</b>\n"
    "• 7-day trial: /trial\n"
    "• Redeem key: /redeem &lt;key&gt;\n"
    "• Generate key (OWNER): /genkey &lt;days&gt;\n"
    "• Whitelist: /wl_add &lt;domain&gt; | /wl_del &lt;domain&gt; | /wl_list\n"
    "• Auto-promotion: /ad_on, /ad_off, /ad_set &lt;text&gt;, /ad_interval &lt;minutes&gt;\n"
    "• Change language: /lang vi or /lang en\n"
)

# ------------------------ Helpers ------------------------
async def pro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    txt = HELP_PRO_EN if lang == "en" else HELP_PRO_VI
    await _reply(update, context, txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

def _is_owner(owner_id: int | None, user_id: int) -> bool:
    try:
        return bool(owner_id) and int(owner_id) == int(user_id)
    except Exception:
        return False

async def _admin_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Kiểm tra admin nhóm."""
    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        m = await context.bot.get_chat_member(chat_id, user_id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

def _ensure_user(db: SessionLocal, user_id: int, username: str | None) -> User:
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if not u:
        u = User(id=user_id, username=username or "")
        db.add(u)
        db.flush()
    return u

# ------------------------ PRO core ------------------------
async def trial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    u = update.effective_user
    db = SessionLocal()
    try:
        user = _ensure_user(db, u.id, u.username)
        now = now_aw()

        # đang PRO còn hạn -> báo lại
        exp = ensure_aware(user.pro_expires_at)
        if user.is_pro and exp and exp > now:
            remain = exp - now
            days = max(0, remain.days)
            return await _reply(update, context, t(lang, "trial_active", days=days))

        # đã từng trial...
        trow = db.query(Trial).filter_by(user_id=u.id).one_or_none()
        if trow:
            t_exp = ensure_aware(trow.expires_at)
            if trow.active and t_exp and t_exp > now:
                remain = t_exp - now
                d = remain.days
                return await _reply(update, context, t(lang, "trial_active", days=d))
            if not trow.active:
                return await _reply(update, context, t(lang, "trial_end"))

        # cấp trial 7 ngày
        exp_new = now + timedelta(days=7)
        if not trow:
            trow = Trial(user_id=u.id, started_at=now, expires_at=exp_new, active=True)
            db.add(trow)
        else:
            trow.started_at = now
            trow.expires_at = exp_new
            trow.active = True

        user.is_pro = True
        user.pro_expires_at = exp_new
        db.commit()
        await _reply(update, context, t(lang, "trial_started"))
    finally:
        db.close()

async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not context.args:
        return await _reply(update, context, t(lang, "redeem_usage"), parse_mode=ParseMode.HTML)

    key = context.args[0].strip()
    db = SessionLocal()
    try:
        lk = db.query(LicenseKey).filter_by(key=key).one_or_none()
        if not lk or lk.used:
            return await _reply(update, context, t(lang, "redeem_invalid"))

        u = update.effective_user
        user = _ensure_user(db, u.id, u.username)

        days = lk.days or 30
        user.is_pro = True
        user.pro_expires_at = now_aw() + timedelta(days=days)
        lk.used = True
        lk.issued_to = u.id
        db.commit()
        await _reply(update, context, t(lang, "genkey_created").replace("{days}", str(days)))
    finally:
        db.close()

async def genkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int = 0):
    lang = _lang(update)
    if not _is_owner(owner_id, update.effective_user.id):
        return await _reply(update, context, t(lang, "genkey_denied"))
    days = 30
    if context.args:
        try:
            days = max(1, int(context.args[0]))
        except Exception:
            return await _reply(update, context, t(lang, "genkey_usage"), parse_mode=ParseMode.HTML)

    code = "PRO-" + secrets.token_urlsafe(12).upper()
    db = SessionLocal()
    try:
        lk = LicenseKey(key=code, days=days)
        db.add(lk)
        db.commit()
        await _reply(
            update, context,
            t(lang, "genkey_created").replace("{days}", str(days)).replace("{code}", f"<code>{code}</code>"),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    finally:
        db.close()

# ------------------------ Whitelist ------------------------
async def wl_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await _reply(update, context, "Chỉ admin mới dùng lệnh này. / Admin only.")
    if not context.args:
        return await _reply(update, context, "Cú pháp / Usage: /wl_add domain.com", parse_mode=ParseMode.HTML)
    domain = context.args[0].lower()

    db = SessionLocal()
    try:
        ex = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
        if ex:
            return await _reply(update, context, t(lang, "wl_exists"))
        db.add(Whitelist(chat_id=update.effective_chat.id, domain=domain))
        db.commit()
        await _reply(update, context, t(lang, "wl_added").replace("{domain}", domain))
    finally:
        db.close()

async def wl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await _reply(update, context, "Chỉ admin mới dùng lệnh này. / Admin only.")
    if not context.args:
        return await _reply(update, context, "Cú pháp / Usage: /wl_del domain.com", parse_mode=ParseMode.HTML)
    domain = context.args[0].lower()

    db = SessionLocal()
    try:
        it = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
        if not it:
            return await _reply(update, context, t(lang, "wl_not_found"))
        db.delete(it)
        db.commit()
        await _reply(update, context, t(lang, "wl_deleted").replace("{domain}", domain))
    finally:
        db.close()

async def wl_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    db = SessionLocal()
    try:
        items = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id).all()
        if not items:
            return await _reply(update, context, t(lang, "wl_empty"))
        out = "\n".join(f"• {i.domain}" for i in items)
        await _reply(update, context, out, disable_web_page_preview=True)
    finally:
        db.close()

# ------------------------ Quảng cáo tự động ------------------------
async def ad_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await _reply(update, context, "Chỉ admin mới dùng lệnh này. / Admin only.")
    db = SessionLocal()
    try:
        if not _has_active_pro(db, update.effective_user.id):
            return await _reply(update, context, t(lang, "need_pro"))

        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, is_enabled=True)
            db.add(s)
        else:
            s.is_enabled = True
        db.commit()
        await _reply(update, context, t(lang, "pro_on"))
    finally:
        db.close()

async def ad_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await _reply(update, context, "Chỉ admin mới dùng lệnh này. / Admin only.")
    db = SessionLocal()
    try:
        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, is_enabled=False)
            db.add(s)
        else:
            s.is_enabled = False
        db.commit()
        await _reply(update, context, t(lang, "pro_off"))
    finally:
        db.close()

async def ad_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await _reply(update, context, "Chỉ admin mới dùng lệnh này. / Admin only.")
    text = " ".join(context.args).strip()
    if not text:
        return await _reply(update, context, "Cú pháp / Usage: /ad_set <nội dung | content>", parse_mode=ParseMode.HTML)

    db = SessionLocal()
    try:
        if not _has_active_pro(db, update.effective_user.id):
            return await _reply(update, context, t(lang, "need_pro"))

        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, is_enabled=True, content=text)
            db.add(s)
        else:
            s.content = text
        db.commit()
        await _reply(update, context, t(lang, "ad_updated"))
    finally:
        db.close()

async def ad_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await _reply(update, context, "Chỉ admin mới dùng lệnh này. / Admin only.")
    if not context.args:
        return await _reply(update, context, "Cú pháp / Usage: /ad_interval <phút/minutes>", parse_mode=ParseMode.HTML)
    try:
        minutes = max(10, int(context.args[0]))
    except Exception:
        return await _reply(update, context, "Giá trị không hợp lệ / Invalid value.")

    db = SessionLocal()
    try:
        if not _has_active_pro(db, update.effective_user.id):
            return await _reply(update, context, t(lang, "need_pro"))

        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, is_enabled=True, interval_minutes=minutes)
            db.add(s)
        else:
            s.interval_minutes = minutes
        s.last_sent_at = None
        db.commit()
        await _reply(update, context, t(lang, "ad_interval_set").replace("{minutes}", str(minutes)))
    finally:
        db.close()

# ----------- Trạng thái quảng cáo (/ad_status) -----------
def _fmt_ts(dt):
    if not dt:
        return "—"
    try:
        return ensure_aware(dt).astimezone(_tz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(dt)

async def ad_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    db = SessionLocal()
    try:
        chat_id = update.effective_chat.id
        s = db.query(PromoSetting).filter_by(chat_id=chat_id).one_or_none()

        if not s:
            await _reply(update, context, t(lang, "wl_empty"))
            return

        msg = (
            f"📊 <b>{t(lang, 'ad_status_title')}</b>\n"
            f"• {t(lang,'ad_status_enabled')}: {'✅' if s.is_enabled else '❎'}\n"
            f"• {t(lang,'ad_status_interval')}: {s.interval_minutes} phút\n"
            f"• {t(lang,'ad_status_content')}: {('OK' if (s.content or '').strip() else '—')}\n"
            f"• {t(lang,'ad_status_last')}: {_fmt_ts(s.last_sent_at)}"
        )
        await _reply(update, context, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    finally:
        db.close()

# ------------------------ Register ------------------------
def register_handlers(app: Application, owner_id: int | None = None):
    app.add_handler(CommandHandler("lang", lang_cmd))

    app.add_handler(CommandHandler("pro", pro_cmd))
    app.add_handler(CommandHandler("trial", trial_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("genkey", lambda u, c: genkey_cmd(u, c, owner_id or 0)))

    # ❗ FREE xử lý /wl_add trong main.py. Ở PRO chỉ đăng ký del/list để tránh trùng lệnh.
    # app.add_handler(CommandHandler("wl_add", wl_add))
    app.add_handler(CommandHandler("wl_del", wl_del))
    app.add_handler(CommandHandler("wl_list", wl_list))

    # Quảng cáo tự động (admin, cần PRO/TRIAL)
    app.add_handler(CommandHandler("ad_on", ad_on))
    app.add_handler(CommandHandler("ad_off", ad_off))
    app.add_handler(CommandHandler("ad_set", ad_set))
    app.add_handler(CommandHandler("ad_interval", ad_interval))
    app.add_handler(CommandHandler("ad_status", ad_status))
