from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from pytz import utc
from telegram.constants import ParseMode

from core.models import SessionLocal, User, Trial, PromoSetting, now_utc


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


def _promo_tick(app):
    """Gửi quảng cáo tự động theo chu kỳ"""
    db = SessionLocal()
    try:
        now = now_utc()
        promos = db.query(PromoSetting).filter(PromoSetting.is_enabled == True).all()

        for ps in promos:
            if not ps.content or not ps.chat_id:
                continue

            interval = ps.interval_minutes or 60
            last = ps.last_sent_at or (now - timedelta(minutes=interval + 1))

            # Nếu đã quá hạn thì gửi
            if (now - last).total_seconds() >= interval * 60:
                print(f"[promo_tick] gửi QC -> chat_id={ps.chat_id}")
                try:
                    app.bot.send_message(
                        ps.chat_id,
                        ps.content,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    print(f"[promo_tick] lỗi gửi QC: {e}")

                # Cập nhật thời gian gửi gần nhất
                ps.last_sent_at = now

        db.commit()

    except Exception as e:
        print("[promo_tick] lỗi tick:", e)
    finally:
        db.close()


def attach_scheduler(app):
    """
    Gắn lịch kiểm tra tự động vào bot:
    - Chạy mỗi 30 phút để kiểm tra hạn gói PRO & TRIAL.
    - Chạy mỗi 1 phút để kiểm tra quảng cáo tự động.
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

        # Gửi quảng cáo tự động mỗi 1 phút
        sched.add_job(
            _promo_tick,
            trigger=IntervalTrigger(minutes=1),
            args=[app],
            id="promo_tick",
            replace_existing=True
        )

        sched.start()
        app.bot_data["scheduler"] = sched
        print("✅ Scheduler: đã bật kiểm tra hạn PRO & quảng cáo tự động")

    except Exception as e:
        print("❌ Lỗi attach_scheduler:", e)
