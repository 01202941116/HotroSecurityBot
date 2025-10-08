def help_cmd(update, context):
    """Hiển thị hướng dẫn chi tiết cho người dùng (Free / Pro)."""
    chat = update.effective_chat
    user_id = update.effective_user.id

    # Chỉ admin mới thấy help chi tiết trong group
    if chat.type in ("group", "supergroup") and not is_admin(user_id):
        return

    s = get_setting(chat.id)
    pro = is_pro(chat.id)
    trial = not s["trial_used"]

    # --- Phần hiển thị /help ---
    text = f"""🛡 *HƯỚNG DẪN SỬ DỤNG {'(PRO)' if pro else '(FREE)'}*

📍 *Bước 1 — Chuẩn bị*
• Thêm bot vào nhóm & cấp quyền *Xoá tin nhắn*.
• Nếu muốn nhận thông báo riêng, hãy nhắn /start cho bot ở cửa sổ riêng.

📌 *Lệnh quản lý nhóm*
/status – Xem cấu hình & thời hạn Pro
/nolinks on|off – Bật/tắt chặn link & @mention
/noforwards on|off – Chặn tin forward
/nobots on|off – Cấm mời bot vào nhóm
/noevents on|off – Ẩn thông báo join/leave (Pro)
/antiflood on|off – Chống spam 3 tin / 20s (Pro)

📜 *Danh sách kiểm soát*
/whitelist_add <từ> – Cho phép nội dung/link này
/whitelist_remove <từ> – Xoá khỏi whitelist
/whitelist_list – Xem danh sách whitelist

/blacklist_add <từ> – Cấm nội dung chứa từ này
/blacklist_remove <từ> – Xoá khỏi blacklist
/blacklist_list – Xem danh sách blacklist

🎯 *Lệnh hỗ trợ khác*
/myid – Lấy user_id của bạn
/chatid – Lấy chat_id của nhóm hiện tại

{"🎁 *Dùng thử Pro 7 ngày (admin)*\n/trial7 – Kích hoạt dùng thử cho nhóm hiện tại (chỉ 1 lần)\n" if trial else ""}🔑 *Nâng cấp Pro vĩnh viễn*
/applykey <key> – Kích hoạt / gia hạn Pro
/genkey <tháng> – (Admin) tạo key dùng thử
/keys_list – (Admin) xem danh sách key

🧩 *Cách hoạt động của bộ lọc*
• /nolinks on: Xoá link hoặc @mention (trừ trong whitelist)
• /noforwards on: Xoá tin được forward
• /blacklist_add: Xoá ngay nếu phát hiện từ bị cấm
• /antiflood on: Xoá nếu spam quá 3 tin / 20s
• /noevents on: Ẩn join/leave

📌 *Ghi chú:*
- Admin bot (ID trong ADMIN_IDS) được bỏ qua bộ lọc.
- Hết hạn dùng thử, bot sẽ nhắc gia hạn tự động.
- Nếu bot không nhắn riêng được, hãy /start với bot trước.

💬 *Hỗ trợ:* @Myyduyenng
"""
    safe_reply_private(update, context, text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
