# pro/scheduler.py
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

def _cleanup_job():
    from core.models import SessionLocal, User, Trial
    db = SessionLocal()
    try:
        # Tắt PRO đã hết hạn
        us = db.query(User).all()
        changed = 0
        for u in us:
            if u.is_pro and (not u.pro_expires_at or u.pro_expires_at <= datetime.utcnow()):
                u.is_pro = False
                changed += 1
        if changed:
            db.commit()

        # Tắt Trial hết hạn
        trials = db.query(Trial).filter_by(active=True).all()
        for t in trials:
            if t.expires_at and t.expires_at <= datetime.utcnow():
                t.active = False
        db.commit()
    finally:
        db.close()

_sched = None

def attach_scheduler(app):
    global _sched
    if _sched:
        return
    _sched = BackgroundScheduler(timezone="UTC")
    # chạy mỗi 15 phút
    _sched.add_job(_cleanup_job, "interval", minutes=15, id="pro_cleanup", replace_existing=True)
    _sched.start()
