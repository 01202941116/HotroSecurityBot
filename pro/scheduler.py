# pro/scheduler.py
from datetime import timedelta, timezone as _tz
from pytz import utc
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from telegram.constants import ParseMode

from core.models import (
    SessionLocal, User, Trial, now_utc,
    PromoSetting,
)

# ==== Datetime helpers (UTC-aware) ====
def ensure_aware(dt):
    """Đảm bảo datetime có tzinfo=UTC (aware)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_tz.utc)


# ---------- JOB 1: Hết hạn PRO / TRIAL (chạy bằng APScheduler, sync) ----------
def _expire_pro():
    db = SessionLocal()
    try:
        now = now_utc()

        # Hết hạn PRO
        for u in db.query(User).filter(User.is_pro == True).all():
            exp = ensure_aware(u.pro_expires_at)
            if exp and exp <= now:
                print(f"[SCHEDULER] Hết hạn PRO user_id={u.id}")
                u.is_pro = False
                u.pro_expires_at = None

        # Hết hạn TRIAL
        for t in db.query(Trial).filter(Trial.active == True).all():
            exp = ensure_aware(t.expires_at)
            if exp and exp <= now:
                print(f"[SCHEDULER] Hết hạn TRIAL user_id={t.user_id}")
                t.active = False

        db.commit()
    except Exception as e:
        print("[SCHEDULER] Lỗi khi cập nhật hạn PRO/TRIAL:", e)
    finally:
        db.close()


# ---------- JOB 2: Gửi quảng cáo tự động (chạy bằng PTB JobQueue, async) ----------
async def _promo_tick_job(context):
    """
    Gọi mỗi 60 giây bởi PTB JobQueue. Gửi QC cho các group đủ điều kiện.
    """
    db = SessionLocal()
    sent = 0
    try:
        now = now_utc()
        items = db.query(PromoSetting).filter(PromoSetting.is_enabled == True).all()
        for ps in items:
            # Điều kiện gửi
            if not (ps.content and ps.interval_minutes and ps.interval_minutes >= 10):
                continue

            last = ensure_aware(ps.last_sent_at)
            should_send = (last is None) or ((now - last) >= timedelta(minutes=ps.interval_minutes))
            if not should_send:
                continue

            try:
                await context.bot.send_message(
                    ps.chat_id,
                    ps.content,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                ps.last_sent_at = now
                db.commit()
                sent += 1
                print(f"[promo_tick] sent -> chat_id={ps.chat_id}")
            except Exception as e:
                print(f"[promo_tick] send fail chat_id={ps.chat_id}: {e}")
                # không raise để tiếp tục các chat khác
    except Exception as e:
        print("[promo_tick] error:", e)
    finally:
        db.close()

    if sent:
        print(f"[promo_tick] done, sent={sent}")


# ---------- Public API ----------
def attach_scheduler(app):
    """
    Gắn 2 loại lịch:
      • APScheduler (thread) cho các tác vụ không cần async: hết hạn PRO/TRIAL mỗi 30 phút
      • PTB JobQueue (async) cho quảng cáo tự động: check mỗi 60 giây
    """
    # 1) APScheduler cho hết hạn PRO
    try:
        sched = BackgroundScheduler(timezone=utc)
        sched.add_job(
            _expire_pro,
            trigger=IntervalTrigger(minutes=30),
            id="expire_pro",
            replace_existing=True,
        )
        sched.start()
        app.bot_data["scheduler"] = sched
        print("✅ Scheduler: đã bật kiểm tra hạn PRO mỗi 30 phút")
    except Exception as e:
        print("❌ Lỗi attach APScheduler:", e)

    # 2) PTB JobQueue cho quảng cáo tự động
    try:
        # chạy sau 60s kể từ khi bot lên, rồi lặp mỗi 60s
        app.job_queue.run_repeating(
            _promo_tick_job,
            interval=60,
            first=60,
            name="promo_tick",
        )
        print("✅ JobQueue: promo_tick mỗi 60 giây")
    except Exception as e:
        print("❌ Lỗi attach JobQueue promo_tick:", e)
