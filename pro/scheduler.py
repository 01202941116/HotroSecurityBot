# pro/scheduler.py
from datetime import datetime, timedelta
from telegram.ext import Application

# Gắn các job nền bằng JobQueue có sẵn của PTB (không cần apscheduler)
def attach_scheduler(app: Application):
    jq = app.job_queue

    # Ping keepalive 5 phút/lần để Render free đỡ ngủ (nếu bạn có flask keepalive thì có thể bỏ)
    async def _ping_keepalive(_):
        try:
            import os, requests
            url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEPALIVE_URL")
            if url:
                requests.get(url, timeout=5)
        except Exception:
            pass

    # Kiểm tra hết hạn trial / pro mỗi 30 phút (ví dụ)
    async def _check_expiry(_):
        try:
            from core.models import SessionLocal, User
            now = datetime.utcnow()
            db = SessionLocal()
            for u in db.query(User).filter(User.pro_expires_at != None).all():  # noqa: E711
                if u.pro_expires_at <= now:
                    u.is_pro = False
                    u.pro_expires_at = None
            db.commit()
        except Exception:
            pass

    jq.run_repeating(_ping_keepalive, interval=5*60, first=10)
    jq.run_repeating(_check_expiry,  interval=30*60, first=30)
