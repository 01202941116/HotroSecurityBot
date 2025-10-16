# core/lang.py

# ====== GỐC NGÔN NGỮ ======
LANG = {
    "vi": {
        "start": "Chào {name} 👋\nHiện có {count} người đang sử dụng bot.",
        "pro_on": "✅ Đã bật quảng cáo tự động cho nhóm này.",
        "pro_off": "⛔️ Đã tắt quảng cáo tự động.",
        "trial_active": "✅ Bạn đang dùng thử, còn {days} ngày.",
        "trial_end": "❗ Thời gian dùng thử đã kết thúc.",
        "need_pro": "❗ Tính năng này chỉ dành cho người dùng còn PRO/TRIAL.",
    },
    "en": {
        "start": "Hello {name} 👋\nThere are currently {count} users using this bot.",
        "pro_on": "✅ Auto-promotion enabled for this group.",
        "pro_off": "⛔️ Auto-promotion disabled.",
        "trial_active": "✅ You are on trial, {days} days remaining.",
        "trial_end": "❗ Your trial period has expired.",
        "need_pro": "❗ This feature is available for PRO/TRIAL users only.",
    }
}

# ====== BỔ SUNG NGÔN NGỮ ======
LANG["vi"].update({
    "lang_switched": "✅ Đã đổi ngôn ngữ sang: VI",
    "lang_usage": "Dùng: /lang vi hoặc /lang en",
    "help_full": (
        "🤖 <b>HotroSecurityBot – Hỗ trợ quản lý nhóm Telegram</b>\n"
        "Tự động lọc spam, chặn link, cảnh báo vi phạm và quản lý quảng cáo thông minh.\n\n"
        "🆓 <b>GÓI FREE</b>\n"
        "• /filter_add &lt;từ&gt; – Thêm từ khoá cần chặn\n"
        "• /filter_list – Xem danh sách từ khoá đã chặn\n"
        "• /filter_del &lt;id&gt; – Xoá filter theo ID\n"
        "• /antilink_on | /antilink_off – Bật/tắt chặn link\n"
        "• /antimention_on | /antimention_off – Bật/tắt chặn tag @all / mention\n"
        "• /antiforward_on | /antiforward_off – Bật/tắt chặn tin chuyển tiếp\n"
        "• /setflood &lt;n&gt; – Giới hạn spam tin nhắn (mặc định 3)\n\n"
        "💎 <b>GÓI PRO</b>\n"
        "• /pro – Hướng dẫn dùng thử & kích hoạt PRO\n"
        "• /trial – Dùng thử miễn phí 7 ngày\n"
        "• /redeem &lt;key&gt; – Kích hoạt key PRO\n"
        "• /genkey &lt;days&gt; – (OWNER) Tạo key PRO\n"
        "• /wl_add &lt;domain&gt; | /wl_del &lt;domain&gt; | /wl_list – Quản lý whitelist\n"
        "• /warn – (Admin) Reply tin có link để cảnh báo/xoá link/chặn khi vi phạm 3 lần\n\n"
        "• /warn_info – Xem số cảnh cáo của 1 người (reply tin hoặc /warn_info &lt;user_id&gt;)\n"
        "• /warn_clear – Xóa toàn bộ cảnh cáo của 1 người (reply tin hoặc /warn_clear &lt;user_id&gt;)\n"
        "• /warn_top – Xem top người bị cảnh cáo nhiều nhất\n"
        "• /support_on – Bật chế độ hỗ trợ (người hỗ trợ được gửi link)"
        "• /support_off – Tắt chế độ hỗ trợ"
        "• /support_add (reply) – Thêm người hỗ trợ"
        "• /support_del (reply) – Xoá người hỗ trợ"
        "• /support_list – Xem danh sách người hỗ trợ"


        "📢 <b>QUẢNG CÁO TỰ ĐỘNG</b>\n"
        "• /ad_on – Bật QC tự động\n"
        "• /ad_off – Tắt QC tự động\n"
        "• /ad_set &lt;nội dung&gt; – Đặt nội dung QC\n"
        "• /ad_interval &lt;phút&gt; – Chu kỳ gửi (mặc định 60)\n"
        "• /ad_status – Xem trạng thái QC\n\n"
        "🌐 <b>Ngôn ngữ</b>\n"
        "• /lang vi — Tiếng Việt\n"
        "• /lang en — English\n"
    ),
})

LANG["en"].update({
    "lang_switched": "✅ Switched language to: EN",
    "lang_usage": "Usage: /lang vi or /lang en",
    "help_full": (
        "🤖 <b>HotroSecurityBot – Group Security Assistant</b>\n"
        "Auto filter spam, block links, warn violators, and schedule promo posts.\n\n"
        "🆓 <b>FREE</b>\n"
        "• /filter_add &lt;word&gt; – Add blocked keyword\n"
        "• /filter_list – List blocked keywords\n"
        "• /filter_del &lt;id&gt; – Delete a filter by ID\n"
        "• /antilink_on | /antilink_off – Toggle link blocking\n"
        "• /antimention_on | /antimention_off – Toggle @ mention blocking\n"
        "• /antiforward_on | /antiforward_off – Toggle forwarded message blocking\n"
        "• /setflood &lt;n&gt; – Anti-flood limit (default 3)\n\n"
        "💎 <b>PRO</b>\n"
        "• /pro – PRO guide & activation\n"
        "• /trial – 7-day free trial\n"
        "• /redeem &lt;key&gt; – Redeem PRO key\n"
        "• /genkey &lt;days&gt; – (OWNER) Generate PRO key\n"
        "• /wl_add &lt;domain&gt; | /wl_del &lt;domain&gt; | /wl_list – Whitelist manager\n"
        "• /warn – (Admin) Reply a message with link to warn/delete/auto-ban after 3 times\n\n"
        "• /warn_info – Show a member’s warning count (reply a message or /warn_info &lt;user_id&gt;)\n"
        "• /warn_clear – Clear all warnings of a member (reply a message or /warn_clear &lt;user_id&gt;)\n"
        "• /warn_top – Show top members with the most warnings\n"
        "• /support_on – Enable Support Mode (supporters can send links)"
        "• /support_off – Disable Support Mode"
        "• /support_add (reply) – Add a supporter"
        "• /support_del (reply) – Remove a supporter"
        "• /support_list – Show supporters"
        "📢 <b>AUTO PROMOTION</b>\n"
        "• /ad_on – Enable auto promo\n"
        "• /ad_off – Disable auto promo\n"
        "• /ad_set &lt;text&gt; – Set promo content\n"
        "• /ad_interval &lt;minutes&gt; – Posting interval (default 60)\n"
        "• /ad_status – Promo status\n\n"
        "🌐 <b>Language</b>\n"
        "• /lang vi — Vietnamese\n"
        "• /lang en — English\n"
    ),
})

# ====== HÀM TRỢ GIÚP ======
def t(lang: str, key: str, **kwargs):
    """Trả về text theo ngôn ngữ (mặc định tiếng Việt nếu không có)."""
    lang = lang if lang in LANG else "vi"
    text = LANG[lang].get(key, key)
    try:
        return text.format(**kwargs)
    except Exception:
        return text
