async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    admin_user = update.effective_user

    # bắt buộc reply tới tin có link
    if not msg.reply_to_message:
        return await msg.reply_text("Hãy reply vào tin có link rồi gõ /warn")

    # chỉ admin/creator được dùng
    try:
        member = await context.bot.get_chat_member(chat_id, admin_user.id)
        if member.status not in ("administrator", "creator"):
            return await msg.reply_text("Chỉ admin mới dùng lệnh này.")
    except Exception:
        return await msg.reply_text("Không thể kiểm tra quyền admin.")

    target_msg = msg.reply_to_message
    target_user = target_msg.from_user
    text = (target_msg.text or target_msg.caption or "")

    if not LINK_RE.search(text):
        return await msg.reply_text("Tin được reply không chứa link.")

    db = SessionLocal()

    # link thuộc whitelist -> không xử lý
    wl = [w.domain for w in db.query(Whitelist).filter_by(chat_id=chat_id).all()]
    if any(d and d.lower() in text.lower() for d in wl):
        db.close()
        return await msg.reply_text("Domain này nằm trong whitelist, không cảnh báo.")

    # XÓA tin gốc & thông báo bản đã loại link
    try:
        await target_msg.delete()
    except Exception:
        pass

    safe_text = remove_links(text)
    try:
        await context.bot.send_message(chat_id, f"🔒 Tin đã xóa link: {safe_text}")
    except Exception:
        pass

    # cập nhật warning count
    w = db.query(Warning).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
    if not w:
        w = Warning(chat_id=chat_id, user_id=target_user.id, count=1)
        db.add(w)
    else:
        w.count += 1
        w.last_warned = func.now()
    db.commit()

    await context.bot.send_message(
        chat_id,
        f"⚠️ <b>Cảnh báo:</b> <a href='tg://user?id={target_user.id}'>Người này</a> đã chia sẻ link không được phép. ({w.count}/3)",
        parse_mode=ParseMode.HTML
    )

    # đủ 3 lần -> thêm blacklist + restrict (tùy chọn)
    if w.count >= 3:
        bl = db.query(Blacklist).filter_by(chat_id=chat_id, user_id=target_user.id).one_or_none()
        if not bl:
            db.add(Blacklist(chat_id=chat_id, user_id=target_user.id))
        db.commit()

        await context.bot.send_message(
            chat_id,
            f"🚫 <b>Đã đưa vào danh sách đen:</b> <a href='tg://user?id={target_user.id}'>Người này</a>.",
            parse_mode=ParseMode.HTML
        )

        # tùy chọn: cấm gửi tin dài hạn
        try:
            until = datetime.now() + timedelta(days=365*10)
            await context.bot.restrict_chat_member(
                chat_id, target_user.id,
                ChatPermissions(can_send_messages=False),
                until_date=until
            )
        except Exception:
            pass

        # nếu muốn reset lại count sau khi vào blacklist:
        # w.count = 0; db.commit()

    db.close()
