# core/lang.py

# ====== GỐC NGÔN NGỮ ======
LANG = {
    "vi": {
        # Chung
        "start": "Chào {name} 👋\nHiện có {count} người đang sử dụng bot.",
        "lang_switched": "✅ Đã đổi ngôn ngữ sang: VI",
        "lang_usage": "Dùng: /lang vi hoặc /lang en",

        # PRO / Trial / Redeem
        "pro_on": "✅ Đã bật quảng cáo tự động cho nhóm này.",
        "pro_off": "⛔️ Đã tắt quảng cáo tự động.",
        "need_pro": "❗ Tính năng này chỉ dành cho người dùng còn PRO/TRIAL.",

        "trial_active": "✅ Bạn đang dùng thử, còn {days} ngày.",
        "trial_end": "❗ Thời gian dùng thử đã kết thúc.",
        "trial_started": "✅ Bắt đầu dùng thử 7 ngày. Chúc bạn trải nghiệm vui vẻ!",
        "pro_active": "✅ Bạn đang có gói PRO, còn {days} ngày.",

        # Redeem / Genkey
        "redeem_usage": "Dùng: <code>/redeem &lt;key&gt;</code>",
        "redeem_invalid": "❗ Key không hợp lệ hoặc đã được sử dụng.",
        "redeem_ok": "✅ Đã kích hoạt PRO {days} ngày. Cảm ơn!",
        "genkey_denied": "❌ Lệnh này chỉ dành cho OWNER.",
        "genkey_usage": "Dùng: <code>/genkey &lt;days&gt;</code>",
        "genkey_created": "✅ Đã tạo key PRO {days} ngày:\n{code}",

        # Whitelist
        "wl_not_found": "❗ Không tìm thấy domain trong whitelist.",
        "wl_deleted": "🗑️ Đã xoá khỏi whitelist: {domain}",
        "wl_empty": "Danh sách trống.",

        # Quảng cáo
        "ad_updated": "✅ Đã cập nhật nội dung quảng cáo.",
        "ad_interval_set": "✅ Đã đặt chu kỳ gửi: {minutes} phút.",
        "ad_status_title": "Trạng thái Quảng cáo tự động",
        "ad_status_enabled": "Bật",
        "ad_status_interval": "Chu kỳ",
        "ad_status_content": "Nội dung",
        "ad_status_last": "Lần gửi gần nhất",

        # HELP
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
            "• /setflood &lt;n&gt; – Giới hạn spam tin nhắn (mặc định 3)\n"
            "• /nobots_on | /nobots_off – Bật/tắt chặn bot mới vào nhóm\n"
            "• /wl_add &lt;domain&gt; – Thêm domain vào whitelist (FREE)\n"
            "• /setwelcome &lt;câu chào&gt; – Cài lời chào cho nhóm khi có thành viên mới\n"
            "   ⤷ Ví dụ: <code>/setwelcome Chào mừng {name} đến với nhóm ❤️</code>\n\n"
            "• /welcome_ttl &lt;giây&gt; – Đặt thời gian tự xoá tin chào (0 = không xoá)\n"
            "• /clear_cache – Xóa bộ nhớ tạm (cache) toàn hệ thống bot\n"
             "• /antispam_on | /antispam_off – Bật/tắt chống spam ảnh & tin nhắn lặp\n"
            "💎 <b>GÓI PRO</b>\n"
            "• /pro – Hướng dẫn dùng thử & kích hoạt PRO\n"
            "• /trial – Dùng thử miễn phí 7 ngày\n"
            "• /redeem &lt;key&gt; – Kích hoạt key PRO\n"
            "• /wl_del &lt;domain&gt; | /wl_list – Quản lý whitelist (xoá / xem)\n"
            "• /warn – (Admin) Cảnh báo / xoá / chặn khi vi phạm 3 lần\n"
            "• /warn_info – Xem số cảnh cáo của 1 người\n"
            "• /warn_clear – Xoá toàn bộ cảnh cáo của 1 người\n"
            "• /warn_top – Xem top cảnh cáo\n"
            "• /support_on – Bật chế độ hỗ trợ (người hỗ trợ được gửi link)\n"
            "• /support_off – Tắt chế độ hỗ trợ\n"
            "• /support_add – Thêm người hỗ trợ\n"
            "• /support_del – Xoá người hỗ trợ\n"
            "• /support_list – Danh sách người hỗ trợ\n\n"
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

        "setwelcome_usage": "📌 Dùng: /setwelcome <câu chào>. Dùng {name} để thay tên thành viên.",
        "setwelcome_ok": "✅ Đã lưu câu chào thành công!",
        "welcome_default": "Chào mừng {name} đến với nhóm!"
    },

    "en": {
        "start": "Hello {name} 👋\nThere are currently {count} users using this bot.",
        "lang_switched": "✅ Switched language to: EN",
        "lang_usage": "Usage: /lang vi or /lang en",

        "pro_on": "✅ Auto-promotion enabled for this group.",
        "pro_off": "⛔️ Auto-promotion disabled.",
        "need_pro": "❗ This feature is available for PRO/TRIAL users only.",

        "trial_active": "✅ You are on trial, {days} days remaining.",
        "trial_end": "❗ Your trial period has expired.",
        "trial_started": "✅ Trial started for 7 days. Enjoy!",
        "pro_active": "✅ You have an active PRO plan, {days} days left.",

        "redeem_usage": "Usage: <code>/redeem &lt;key&gt;</code>",
        "redeem_invalid": "❗ Invalid key or already used.",
        "redeem_ok": "✅ PRO activated for {days} days. Thank you!",
        "genkey_denied": "❌ This command is for OWNER only.",
        "genkey_usage": "Usage: <code>/genkey &lt;days&gt;</code>",
        "genkey_created": "✅ Created a PRO key for {days} days:\n{code}",

        "wl_not_found": "❗ Domain not found in whitelist.",
        "wl_deleted": "🗑️ Removed from whitelist: {domain}",
        "wl_empty": "Empty list.",

        "ad_updated": "✅ Promo content updated.",
        "ad_interval_set": "✅ Posting interval set to {minutes} minutes.",
        "ad_status_title": "Auto Promotion Status",
        "ad_status_enabled": "Enabled",
        "ad_status_interval": "Interval",
        "ad_status_content": "Content",
        "ad_status_last": "Last sent",

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
            "• /setflood &lt;n&gt; – Anti-flood limit (default 3)\n"
            "• /nobots_on | /nobots_off – Toggle blocking newly-added bots\n"
            "• /wl_add &lt;domain&gt; – Add a domain to whitelist (FREE)\n"
            "• /setwelcome &lt;message&gt; – Set a custom welcome message for new members\n"
            "   ⤷ Example: <code>/setwelcome Welcome {name} to our group 🎉</code>\n\n"
            "• /welcome_ttl <seconds> – Set auto-delete time for welcome messages (0 = never)\n"
            "• /clear_cache – Clear cached memory for all users\n"
            "• /antispam_on | /antispam_off – Enable/disable anti-spam (images & repeated texts)\n"
            "💎 <b>PRO</b>\n"
            "• /pro – PRO guide & activation\n"
            "• /trial – 7-day free trial\n"
            "• /redeem &lt;key&gt; – Redeem PRO key\n"
            "• /wl_del &lt;domain&gt; | /wl_list – Manage whitelist (remove / list)\n"
            "• /warn – (Admin) Warn or auto-ban after 3 violations\n"
            "• /warn_info – Check warning count of a member\n"
            "• /warn_clear – Clear all warnings\n"
            "• /warn_top – Show top warned members\n"
            "• /support_on – Enable Support Mode\n"
            "• /support_off – Disable Support Mode\n"
            "• /support_add – Add a supporter\n"
            "• /support_del – Remove a supporter\n"
            "• /support_list – Show supporters\n\n"
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

        "setwelcome_usage": "📌 Usage: /setwelcome <message>. Use {name} to insert the new member’s name.",
        "setwelcome_ok": "✅ Welcome message saved!",
        "welcome_default": "Welcome {name} to the group!"
    }
}

# ====== HÀM TRỢ GIÚP ======
def t(lang: str, key: str, **kwargs):
    """Trả về text theo ngôn ngữ (mặc định tiếng Việt nếu không có)."""
    lang = lang if lang in LANG else "vi"
    text = LANG[lang].get(key, key)
    try:
        return text.format(**kwargs)
    except Exception:
        return text
