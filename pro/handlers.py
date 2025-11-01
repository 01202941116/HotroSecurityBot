from __future__ import annotations

from core.lang import t  # i18n
from core.models import SessionLocal, SupportSetting, Supporter, list_supporters, get_support_enabled

import secrets
from datetime import timedelta, timezone as _tz
from telegram.ext import CommandHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler
from core.models import (
    SessionLocal,
    User,
    LicenseKey,
    Trial,
    Whitelist,
    PromoSetting,
    now_utc,
    Setting,
)

# ====== i18n: lưu lựa chọn ngôn ngữ RAM ======
USER_LANG: dict[int, str] = {}  # user_id -> "vi" | "en"

def _lang(update: Update) -> str:
    uid = update.effective_user.id if update.effective_user else 0
    return USER_LANG.get(uid, "vi")

# ====== Timezone-safe ======
def ensure_aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_tz.utc)

def now_aw():
    return ensure_aware(now_utc())

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

HELP_PRO_VI = (
    "<b>Gói PRO</b>\n"
    "• Dùng thử 7 ngày: /trial\n"
    "• Nhập key: /redeem &lt;key&gt;\n"    
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

# ------------------------ Helpers ------------------------
async def pro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    txt = HELP_PRO_EN if lang == "en" else HELP_PRO_VI
    await m.reply_text(txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

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
async def _toggle_setting(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          field: str, value: bool, label: str):
    m = update.effective_message
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này. / Admin only.")
    chat_id = update.effective_chat.id
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
        if not s:
            s = Setting(chat_id=chat_id)
            db.add(s); db.flush()
        setattr(s, field, value)
        db.commit()
        await m.reply_text(f"{label}: {'✅ ON' if value else '❎ OFF'}")
    finally:
        db.close()
# ------------------------ PRO core ------------------------
async def trial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    u = update.effective_user
    db = SessionLocal()
    try:
        user = _ensure_user(db, u.id, u.username)
        now = now_aw()

        # 1) Nếu đã có PRO (từ key hoặc do trước đó được set), báo "đang có PRO"
        exp_user = ensure_aware(user.pro_expires_at)
        if user.is_pro and exp_user and exp_user > now:
            remain = exp_user - now
            days = max(0, remain.days)
            return await m.reply_text(t(lang, "pro_active", days=days))

        # 2) Nếu đã có TRIAL còn hạn -> báo "đang dùng thử"
        trow = db.query(Trial).filter_by(user_id=u.id).one_or_none()
        if trow:
            t_exp = ensure_aware(trow.expires_at)
            if trow.active and t_exp and t_exp > now:
                d = (t_exp - now).days
                return await m.reply_text(t(lang, "trial_active", days=d))
            # đã từng trial nhưng hết hạn -> không cấp lại
            return await m.reply_text(t(lang, "trial_end"))

        # 3) Chưa từng trial -> cấp 7 ngày + set PRO = True trong 7 ngày đó
        exp_new = now + timedelta(days=7)
        db.add(Trial(user_id=u.id, started_at=now, expires_at=exp_new, active=True))
        user.is_pro = True
        user.pro_expires_at = exp_new
        db.commit()
        return await m.reply_text(t(lang, "trial_started"))
    finally:
        db.close()

async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    if not context.args:
        return await m.reply_text(t(lang, "redeem_usage"), parse_mode=ParseMode.HTML)

    key = context.args[0].strip()
    db = SessionLocal()
    try:
        lk = db.query(LicenseKey).filter_by(key=key).one_or_none()
        if not lk or lk.used:
            return await m.reply_text(t(lang, "redeem_invalid"))

        u = update.effective_user
        user = _ensure_user(db, u.id, u.username)

        days = lk.days or 30
        user.is_pro = True
        user.pro_expires_at = now_aw() + timedelta(days=days)

        # tắt trial nếu có
        trow = db.query(Trial).filter_by(user_id=u.id).one_or_none()
        if trow:
            trow.active = False

        lk.used = True
        lk.issued_to = u.id          # cột issued_to là BigInteger → lưu int
        db.commit()
        await m.reply_text(t(lang, "redeem_ok").replace("{days}", str(days)))
    finally:
        db.close()

async def genkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int = 0):
    m = update.effective_message
    lang = _lang(update)
    if not _is_owner(owner_id, update.effective_user.id):
        return await m.reply_text(t(lang, "genkey_denied"))
    days = 30
    if context.args:
        try:
            days = max(1, int(context.args[0]))
        except Exception:
            return await m.reply_text(t(lang, "genkey_usage"), parse_mode=ParseMode.HTML)

    code = "PRO-" + secrets.token_urlsafe(12).upper()
    db = SessionLocal()
    try:
        lk = LicenseKey(key=code, days=days)
        db.add(lk)
        db.commit()
        await m.reply_text(
            t(lang, "genkey_created").replace("{days}", str(days)).replace("{code}", f"<code>{code}</code>"),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    finally:
        db.close()
   async def _toggle_setting(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          field: str, value: bool, label: str):
    """Bật/tắt một cờ boolean trong bảng settings cho group hiện tại."""
    m = update.effective_message
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này. / Admin only.")
    chat_id = update.effective_chat.id
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
        if not s:
            s = Setting(chat_id=chat_id)
            db.add(s)
            db.flush()
        setattr(s, field, value)
        db.commit()
        await m.reply_text(f"{label}: {'✅ ON' if value else '❎ OFF'}")
    finally:
        db.close()     

# ------------------------ Whitelist (PRO: wl_del, wl_list) ------------------------
async def wl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này. / Admin only.")
    if not context.args:
        return await m.reply_text("Cú pháp / Usage: /wl_del domain.com", parse_mode=ParseMode.HTML)
    domain = (context.args[0] or "").lower().strip().strip("/")

    db = SessionLocal()
    try:
        it = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id, domain=domain).one_or_none()
        if not it:
            return await m.reply_text(t(lang, "wl_not_found"))
        db.delete(it)
        db.commit()
        await m.reply_text(t(lang, "wl_deleted").replace("{domain}", domain))
    finally:
        db.close()

async def wl_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    db = SessionLocal()
    try:
        items = db.query(Whitelist).filter_by(chat_id=update.effective_chat.id).all()
        if not items:
            return await m.reply_text(t(lang, "wl_empty"))
        out = "\n".join(f"• {i.domain}" for i in items)
        await m.reply_text(out, disable_web_page_preview=True)
    finally:
        db.close()
        
# ------------------------ Anti-spam toggle ------------------------
async def antispam_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_setting(update, context, "antispam", True, "Anti-spam")

async def antispam_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_setting(update, context, "antispam", False, "Anti-spam")

# ------------------------ Quảng cáo tự động ------------------------
async def ad_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này. / Admin only.")
    db = SessionLocal()
    try:
        if not _has_active_pro(db, update.effective_user.id):
            return await m.reply_text(t(lang, "need_pro"))

        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            from core.models import PromoSetting as PS
            s = PS(chat_id=update.effective_chat.id, is_enabled=True)
            db.add(s)
        else:
            s.is_enabled = True
        db.commit()
        await m.reply_text(t(lang, "pro_on"))
    finally:
        db.close()

async def ad_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này. / Admin only.")
    db = SessionLocal()
    try:
        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            from core.models import PromoSetting as PS
            s = PS(chat_id=update.effective_chat.id, is_enabled=False)
            db.add(s)
        else:
            s.is_enabled = False
        db.commit()
        await m.reply_text(t(lang, "pro_off"))
    finally:
        db.close()

async def ad_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này. / Admin only.")
    text = " ".join(context.args).strip()
    if not text:
        return await m.reply_text("Cú pháp / Usage: /ad_set <nội dung | content>", parse_mode=ParseMode.HTML)

    db = SessionLocal()
    try:
        if not _has_active_pro(db, update.effective_user.id):
            return await m.reply_text(t(lang, "need_pro"))

        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            from core.models import PromoSetting as PS
            s = PS(chat_id=update.effective_chat.id, is_enabled=True, content=text)
            db.add(s)
        else:
            s.content = text
        db.commit()
        await m.reply_text(t(lang, "ad_updated"))
    finally:
        db.close()

async def ad_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này. / Admin only.")
    if not context.args:
        return await m.reply_text("Cú pháp / Usage: /ad_interval <phút/minutes>", parse_mode=ParseMode.HTML)
    try:
        minutes = max(10, int(context.args[0]))
    except Exception:
        return await m.reply_text("Giá trị không hợp lệ / Invalid value.")

    db = SessionLocal()
    try:
        if not _has_active_pro(db, update.effective_user.id):
            return await m.reply_text(t(lang, "need_pro"))

        s = db.query(PromoSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            from core.models import PromoSetting as PS
            s = PS(chat_id=update.effective_chat.id, is_enabled=True, interval_minutes=minutes)
            db.add(s)
        else:
            s.interval_minutes = minutes
        s.last_sent_at = None
        db.commit()
        await m.reply_text(t(lang, "ad_interval_set").replace("{minutes}", str(minutes)))
    finally:
        db.close()

def _fmt_ts(dt):
    if not dt:
        return "—"
    try:
        return ensure_aware(dt).astimezone(_tz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(dt)

async def ad_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    lang = _lang(update)
    db = SessionLocal()
    try:
        chat_id = update.effective_chat.id
        s = db.query(PromoSetting).filter_by(chat_id=chat_id).one_or_none()

        if not s:
            await m.reply_text(t(lang, "wl_empty"))
            return

        msg = (
            f"📊 <b>{t(lang, 'ad_status_title')}</b>\n"
            f"• {t(lang,'ad_status_enabled')}: {'✅' if s.is_enabled else '❎'}\n"
            f"• {t(lang,'ad_status_interval')}: {s.interval_minutes} phút\n"
            f"• {t(lang,'ad_status_content')}: {('OK' if (s.content or '').strip() else '—')}\n"
            f"• {t(lang,'ad_status_last')}: {_fmt_ts(s.last_sent_at)}"
        )
        await m.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    finally:
        db.close()

# ===================== CLEAR PERSONAL CACHE =====================
# Dữ liệu cache riêng cho từng người (user_id: data)
USER_CACHE: dict[int, dict] = {}

def clear_personal_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /clear_cache – Xóa cache riêng của người dùng"""
    user_id = update.effective_user.id
    user_lang = "vi"  # mặc định tiếng Việt

    code = (getattr(update.effective_user, "language_code", "") or "").lower()
    if code.startswith("en"):
        user_lang = "en"

    if user_id in USER_CACHE:
        USER_CACHE.pop(user_id, None)
        msg = "✅ Your cache has been cleared!" if user_lang == "en" else "✅ Đã xóa dữ liệu tạm (cache) của bạn!"
    else:
        msg = "ℹ️ You don't have any saved cache." if user_lang == "en" else "ℹ️ Bạn hiện không có dữ liệu cache nào."

    try:
        update.message.reply_text(msg)
    except Exception:
        pass
        
        # ===================== CLEAR PERSONAL CACHE =====================
# Dữ liệu cache riêng cho từng người (user_id: data)
USER_CACHE = {}

def clear_personal_cache(update, context):
    """Lệnh /clear_cache – Xóa cache riêng của người dùng"""
    user_id = update.effective_user.id
    user_lang = "vi"  # mặc định tiếng Việt

    # Xác định ngôn ngữ Telegram của người dùng
    if hasattr(update.effective_user, "language_code"):
        code = (update.effective_user.language_code or "").lower()
        if code.startswith("en"):
            user_lang = "en"

    # Nếu người dùng có cache → xóa riêng của họ
    if user_id in USER_CACHE:
        USER_CACHE.pop(user_id, None)
        if user_lang == "en":
            msg = "✅ Your cache has been cleared!"
        else:
            msg = "✅ Đã xóa dữ liệu tạm (cache) của bạn!"
    else:
        if user_lang == "en":
            msg = "ℹ️ You don't have any saved cache."
        else:
            msg = "ℹ️ Bạn hiện không có dữ liệu cache nào."

    try:
        update.message.reply_text(msg)
    except Exception:
        pass


def register_clear_cache(dp):
    """Đăng ký lệnh /clear_cache"""
    dp.add_handler(CommandHandler("clear_cache", clear_personal_cache))

# ------------------------ Register ------------------------
def register_handlers(app: Application, owner_id: int | None = None):
    # /lang đã được đăng ký ở main.py (tránh trùng)
    app.add_handler(CommandHandler("pro", pro_cmd))
    app.add_handler(CommandHandler("trial",  trial_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("genkey", lambda u, c: genkey_cmd(u, c, owner_id or 0)))
    # Support Mode
    app.add_handler(CommandHandler("support_on", support_on))
    app.add_handler(CommandHandler("support_off", support_off))
    app.add_handler(CommandHandler("support_add", support_add))
    app.add_handler(CommandHandler("support_del", support_del))
    app.add_handler(CommandHandler("support_list", support_list))

    # IMPORTANT: KHÔNG đăng ký /wl_add ở đây (FREE). PRO chỉ có:
    app.add_handler(CommandHandler("wl_del", wl_del))
    app.add_handler(CommandHandler("wl_list", wl_list))
        # Anti-spam
    app.add_handler(CommandHandler("antispam_on", antispam_on))
    app.add_handler(CommandHandler("antispam_off", antispam_off))
    app.add_handler(CommandHandler("clear_cache", clear_personal_cache))

    # Quảng cáo tự động
    app.add_handler(CommandHandler("ad_on", ad_on))
    app.add_handler(CommandHandler("ad_off", ad_off))
    app.add_handler(CommandHandler("ad_set", ad_set))
    app.add_handler(CommandHandler("ad_interval", ad_interval))
    app.add_handler(CommandHandler("ad_status", ad_status))
    # ---------- SUPPORT MODE (per-group) ----------
async def _admin_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

async def support_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này.")
    db = SessionLocal()
    try:
        s = db.query(SupportSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = SupportSetting(chat_id=update.effective_chat.id, is_enabled=True)
            db.add(s)
        else:
            s.is_enabled = True
        db.commit()
        await m.reply_text("support_on ✅ (người trong danh sách hỗ trợ được gửi link)")
    finally:
        db.close()

async def support_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này.")
    db = SessionLocal()
    try:
        s = db.query(SupportSetting).filter_by(chat_id=update.effective_chat.id).one_or_none()
        if not s:
            s = SupportSetting(chat_id=update.effective_chat.id, is_enabled=False)
            db.add(s)
        else:
            s.is_enabled = False
        db.commit()
        await m.reply_text("support_off ❎ (mọi link kiểm tra như thường)")
    finally:
        db.close()

async def support_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này.")
    if not context.args:
        return await m.reply_text("Dùng: /support_add @username | reply 1 người rồi /support_add")

    # lấy user target từ reply hoặc @username
    target_id = None
    if update.message and update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    if not target_id and context.args:
        username = context.args[0].lstrip("@")
        try:
            user = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        except Exception:
            user = None
        # ưu tiên parse nhanh từ entities nếu có
        for ent in (update.message.entities or []):
            if ent.type == "mention":
                pass
        # nếu không có reply, yêu cầu reply để chắc chắn ID
        if not target_id:
            return await m.reply_text("Vui lòng reply vào người cần thêm rồi gõ /support_add")

    db = SessionLocal()
    try:
        if not get_support_enabled(db, update.effective_chat.id):
            return await m.reply_text("Hãy bật trước bằng /support_on")
        ex = db.query(Supporter).filter_by(chat_id=update.effective_chat.id, user_id=target_id).one_or_none()
        if ex:
            return await m.reply_text("Người này đã trong danh sách hỗ trợ.")
        db.add(Supporter(chat_id=update.effective_chat.id, user_id=target_id))
        db.commit()
        await m.reply_text(f"Đã thêm người hỗ trợ: <a href='tg://user?id={target_id}'>user</a>", parse_mode=ParseMode.HTML)
    finally:
        db.close()

async def support_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    if not await _admin_only(update, context):
        return await m.reply_text("Chỉ admin mới dùng lệnh này.")
    if update.message and update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    else:
        return await m.reply_text("Vui lòng reply vào người cần xoá rồi gõ /support_del")

    db = SessionLocal()
    try:
        it = db.query(Supporter).filter_by(chat_id=update.effective_chat.id, user_id=target_id).one_or_none()
        if not it:
            return await m.reply_text("Không tìm thấy trong danh sách hỗ trợ.")
        db.delete(it)
        db.commit()
        await m.reply_text("Đã xoá khỏi danh sách hỗ trợ.")
    finally:
        db.close()

async def support_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    db = SessionLocal()
    try:
        uids = list_supporters(db, update.effective_chat.id)
        if not get_support_enabled(db, update.effective_chat.id):
            return await m.reply_text("Support mode: ❎\nDanh sách trống.")
        if not uids:
            return await m.reply_text("Support mode: ✅\nChưa có người hỗ trợ.")
        out = ["Support mode: ✅", "• " + "\n• ".join([f"<a href='tg://user?id={x}'>user {x}</a>" for x in uids])]
        await m.reply_text("\n".join(out), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    finally:
        db.close()

