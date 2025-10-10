from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import utc

from core.models import SessionLocal, User, Trial, now_utc

def _expire_pro():
    db = SessionLocal()
    now = now_utc()
    # Hết hạn PRO
    for u in db.query(User).filter(User.is_pro == True).all():
        if u.pro_expires_at and u.pro_expires_at <= now:
            u.is_pro = False
            u.pro_expires_at = None
    # Hết hạn trial
    for t in db.query(Trial).filter(Trial.active == True).all():
        if t.expires_at and t.expires_at <= now:
            t.active = False
    db.commit()

def attach_scheduler(app):
    # chạy mỗi 30 phút kiểm tra hạn
    sched = BackgroundScheduler(timezone=utc)
    sched.add_job(_expire_pro, "interval", minutes=30, id="expire_pro", replace_existing=True)
    sched.start()
    app.bot_data["scheduler"] = sched
