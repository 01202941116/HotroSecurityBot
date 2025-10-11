from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from pytz import utc

from core.models import SessionLocal, User, Trial, now_utc

def _expire_pro():
    """Tự động hết hạn gói PRO & Trial"""
    db = SessionLocal()
    try:
        now = now_utc()

        # Hết hạn PRO
        for u in db.query(User).filter(User.is_pro == True).all():
            if u.pro_expires_at and u.pro_expires_at <= now:
                print(f"[SCHEDULER] Hết hạn PRO user_id={u.user_id}")
                u.is_pro = False
                u.pro_expires_at = None

        # Hết hạn dùng thử
        for t in db.query(Trial).filter(Trial.active == True).all():
            if t.expires_at and t.expires_at <= now:
                print(f"[SCHEDULER] Hết hạn TRIAL user_id={t.user_id}")
                t.active = False

        db.commit()
    except Exception as e:
        print("[SCHEDULER] Lỗi khi cập nhật hạn PRO:", e)
    finally:
        db.close()


def attach_scheduler(app):
    """
    Gắn lịch kiểm tra tự động vào bot
    Chạy mỗi 30 phút để kiểm tra hạn gói PRO & TRIAL.
    """
    try:
        sched = BackgroundScheduler(timezone=utc)

        # Kiểm tra hạn mỗi 30 phút
        sched.add_job(
            _expire_pro,
            trigger=IntervalTrigger(minutes=30),
            id="expire_pro",
            replace_existing=True
        )

        sched.start()
        app.bot_data["scheduler"] = sched
        print("✅ Scheduler: đã bật kiểm tra hạn PRO mỗi 30 phút")

    except Exception as e:
        print("❌ Lỗi attach_scheduler:", e)
