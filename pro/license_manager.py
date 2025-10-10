
from datetime import datetime, timedelta
import secrets, string, os
from sqlalchemy import select
from .models import SessionLocal, User, LicenseKey, Trial

TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "7"))
DEFAULT_DAYS = int(os.getenv("PRO_DEFAULT_DAYS", "30"))

def _random_key():
    alphabet = string.ascii_uppercase + string.digits
    parts = []
    for _ in range(4):
        parts.append("".join(secrets.choice(alphabet) for _ in range(6)))
    return "-".join(parts)

def generate_key(days=DEFAULT_DAYS, tier="pro"):
    db = SessionLocal()
    key = _random_key()
    lk = LicenseKey(key=key, days=days, tier=tier)
    db.add(lk); db.commit()
    return key

def redeem_key(tg_user_id:int, username:str|None, key:str):
    db = SessionLocal()
    lk = db.execute(select(LicenseKey).where(LicenseKey.key==key)).scalar_one_or_none()
    if not lk or lk.used:
        return False, "Key không tồn tại hoặc đã dùng."
    user = db.get(User, tg_user_id) or User(id=tg_user_id, username=username)
    now = datetime.utcnow()
    if user.pro_expires_at and user.pro_expires_at > now:
        user.pro_expires_at = user.pro_expires_at + timedelta(days=lk.days)
    else:
        user.pro_expires_at = now + timedelta(days=lk.days)
    user.is_pro = True
    lk.used = True
    lk.issued_to = tg_user_id
    db.add_all([user, lk]); db.commit()
    return True, f"Đã kích hoạt PRO ({lk.tier}) đến {user.pro_expires_at:%d-%m-%Y %H:%M} UTC."

def start_trial(tg_user_id:int, username:str|None):
    db = SessionLocal()
    tr = db.execute(select(Trial).where(Trial.user_id==tg_user_id)).scalar_one_or_none()
    if tr:
        return False, "Bạn đã dùng thử 1 lần rồi."
    from .models import User
    now = datetime.utcnow()
    tr = Trial(user_id=tg_user_id, started_at=now, expires_at=now+timedelta(days=TRIAL_DAYS), active=True)
    user = db.get(User, tg_user_id) or User(id=tg_user_id, username=username)
    user.is_pro = True
    user.pro_expires_at = tr.expires_at
    db.add_all([tr, user]); db.commit()
    return True, f"Bắt đầu dùng thử PRO {TRIAL_DAYS} ngày. Hết hạn: {tr.expires_at:%d-%m-%Y %H:%M} UTC."

def check_and_downgrade_expired():
    db = SessionLocal()
    now = datetime.utcnow()
    from .models import User, Trial
    users = db.query(User).filter(User.is_pro==True, User.pro_expires_at < now).all()
    for u in users:
        u.is_pro = False
    trials = db.query(Trial).filter(Trial.active==True, Trial.expires_at < now).all()
    for t in trials:
        t.active = False
    db.commit()
    return len(users)
