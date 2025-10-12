# core/lang.py

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

def t(lang: str, key: str, **kwargs):
    """Trả về text theo ngôn ngữ (mặc định tiếng Việt nếu không có)."""
    lang = lang if lang in LANG else "vi"
    text = LANG[lang].get(key, key)
    return text.format(**kwargs)
