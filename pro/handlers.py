from __future__ import annotations
import secrets
import re
from datetime import timedelta, timezone as _tz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from core.lang import t
from core.models import SessionLocal, User, LicenseKey, Trial, Whitelist, PromoSetting, now_utc

# ====== i18n ======
USER_LANG: dict[int, str] = {}  # user_id -> "vi" | "en"

def _lang(update: Update) -> str:
    uid = update.effective_user.id if update.effective_user else 0
    return USER_LANG.get(uid, "vi")

# ====== Safe Reply Helper ======
async def _safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kw):
    msg = update.effective_message
    if msg:
        return await msg.reply_text(text, **kw)
    return await context.bot.send_message(update.effective_chat.id, text, **kw)

# ====== Timezone-safe ======
def ensure_aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_tz.utc)

def now_aw():
    return ensure_aware(now_utc())

# ====== Domain normalize ======
def to_host(domain_or_url: str) -> str:
    s = (domain_or_url or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0].split("?")[0].strip()
    if s.startswith("www."):
        s = s[4:]
    return s

# ====== PRO check ======
def _has_active_pro(db: SessionLocal, user_id: int) -> bool:
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

# ====== Texts ======
HELP_PRO_VI = (
    "<b>Gói PRO</b>\n"
    "• Dùng thử 7 ngày: /trial\n"
    "• Nhập key: /redeem &lt;key&gt;\n"
    "• Tạo key (OWNER): /genkey &lt;days&gt;\n"
    "• Whitelist: /wl_del &lt;domain&gt; | /wl_list (Lưu ý: /wl_add có trong gói FREE)\n"
    "• Quảng cáo tự động nhóm: /ad_on, /ad_off, /ad_set &lt;text&gt;, /ad_interval &lt;phút&gt;\n"
    "• Đổi ngôn ngữ: /lang vi hoặc /lang en\n"
)
HELP_PRO_EN = (
    "<b>PRO Package</b>\n"
    "• 7-day trial: /trial\n"
    "• Redeem key: /redeem &lt;key&gt;\n"
    "• Generate key (OWNER): /genkey &lt;days&gt;\n"
    "• Whitelist: /wl_del &lt;domain&gt; | /wl_list (Note: /wl_add is FREE)\n"
    "• Auto-promotion: /ad_on, /ad_off, /ad_set &lt;text&gt;, /ad_interval &lt;minutes&gt;\n"
    "• Change language: /lang vi or /lang en\n"
)

# ====== Helpers ======
async def pro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    txt = HELP_PRO_EN if lang == "en" else HELP_PRO_VI
    await _safe_reply(update, context, txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

def _is_owner(owner_id: int | None, user_id: int) -> bool:
    try:
        return bool(owner_id) and int(owner_id) == int(user_id)
    except Exception:
        return False

async def _admin_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
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

# ====== PRO core ======
async def trial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    u = update.effective_user
    db = SessionLocal()
    try:
        user = _ensure_user(db, u.id, u.username)
        now = now_aw()
        exp = ensure_aware(user.pro_expires_at)
        if user.is_pro and exp and exp > now:
            remain = exp - now
            days = max(0, remain.days)
            return await _safe_reply(update, context, t(lang, "trial_active", days=days))
        trow = db.query(Trial).filter_by(user_id=u.id).one_or_none()
        if trow:
            t_exp = ensure_aware(trow.expires_at)
            if trow.active and t_exp and t_exp > now:
                d = (t_exp - now).days
                return await _safe_reply(update, context, t(lang, "trial_active", days=d))
            if not trow.active:
                return await _safe_reply(update, context, t(lang, "trial_end"))
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
        await _safe_reply(update, context, t(lang, "trial_started"))
    finally:
        db.close()

async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not context.args:
        return await _safe_reply(update, context, t(lang, "redeem_usage"), parse_mode=ParseMode.HTML)
    key = context.args[0].strip()
    db = SessionLocal()
    try:
        lk = db.query(LicenseKey).filter_by(key=key).one_or_none()
        if not lk or lk.used:
            return await _safe_reply(update, context, t(lang, "redeem_invalid"))
        u = update.effective_user
        user = _ensure_user(db, u.id, u.username)
        days = lk.days or 30
        user.is_pro = True
        user.pro_expires_at = now_aw() + timedelta(days=days)
        lk.used = True
        lk.issued_to = u.id
        db.commit()
        await _safe_reply(update, context, t(lang, "genkey_created").replace("{days}", str(days)))
    finally:
        db.close()

async def genkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int = 0):
    lang = _lang(update)
    if not _is_owner(owner_id, update.effective_user.id):
        return await _safe_reply(update, context, t(lang, "genkey_denied"))
    days = 30
    if context.args:
        try:
            days = max(1, int(context.args[0]))
        except Exception:
            return await _safe_reply(update, context, t(lang, "genkey_usage"), parse_mode=ParseMode.HTML)
    code = "PRO-" + secrets.token_urlsafe(12).upper()
    db = SessionLocal()
    try:
        lk = LicenseKey(key=code, days=days)
        db.add(lk)
        db.commit()
        await _safe_reply(
            update, context,
            t(lang, "genkey_created").replace("{days}", str(days)).replace("{code}", f"<code>{code}</code>"),
            parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )
    finally:
        db.close()

# ====== Whitelist (PRO) ======
async def wl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await _safe_reply(update, context, "Chỉ admin mới dùng lệnh này. / Admin only.")
    if not context.args:
        return await _safe_reply(update, context, "Cú pháp / Usage: /wl_del domain.com", parse_mode=ParseMode.HTML)
    domain = to_host(context.args[0])
    db = SessionLocal()
    try:
        it = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
        if not it:
            return await _safe_reply(update, context, t(lang, "wl_not_found"))
        db.delete(it)
        db.commit()
        await _safe_reply(update, context, t(lang, "wl_deleted").replace("{domain}", domain))
    finally:
        db.close()

async def wl_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    db = SessionLocal()
    try:
        items = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id).all()
        if not items:
            return await _safe_reply(update, context, t(lang, "wl_empty"))
        out = "\n".join(f"• {i.domain}" for i in items)
        await _safe_reply(update, context, out, disable_web_page_preview=True)
    finally:
        db.close()

# ====== Quảng cáo tự động ======
async def ad_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await _safe_reply(update, context, "Chỉ admin mới dùng lệnh này.")
    db = SessionLocal()
    try:
        if not _has_active_pro(db, update.effective_user.id):
            return await _safe_reply(update, context, t(lang, "need_pro"))
        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, is_enabled=True)
            db.add(s)
        else:
            s.is_enabled = True
        db.commit()
        await _safe_reply(update, context, t(lang, "pro_on"))
    finally:
        db.close()

async def ad_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await _safe_reply(update, context, "Chỉ admin mới dùng lệnh này.")
    db = SessionLocal()
    try:
        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = PromoSetting(chat_id=update.effective_chat.id, is_enabled=False)
            db.add(s)
        else:
            s.is_enabled = False
        db.commit()
        await _safe_reply(update, context, t(lang, "pro_off"))
    finally:
        db.close()

# ... giữ nguyên ad_set, ad_interval, ad_status như cũ ...

# ====== Register ======
def register_handlers(app: Application, owner_id: int | None = None):
    app.add_handler(CommandHandler("lang", lang_cmd))
    app.add_handler(CommandHandler("pro", pro_cmd))
    app.add_handler(CommandHandler("trial", trial_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("genkey", lambda u, c: genkey_cmd(u, c, owner_id or 0)))
    app.add_handler(CommandHandler("wl_del", wl_del))
    app.add_handler(CommandHandler("wl_list", wl_list))
    app.add_handler(CommandHandler("ad_on", ad_on))
    app.add_handler(CommandHandler("ad_off", ad_off))
    app.add_handler(CommandHandler("ad_set", ad_set))
    app.add_handler(CommandHandler("ad_interval", ad_interval))
    app.add_handler(CommandHandler("ad_status", ad_status))
