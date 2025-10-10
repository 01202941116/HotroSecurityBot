
from datetime import datetime, timedelta
import secrets, string, os
from sqlalchemy import select
from core.models import SessionLocal, User, LicenseKey, Trial

TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "7"))
DEFAULT_DAYS = int(os.getenv("PRO_DEFAULT_DAYS", "30"))

def _random_key():
    alphabet = string.ascii_uppercase + string.digits
    return "-".join("".join(secrets.choice(alphabet) for _ in range(6)) for _ in range(4))

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
    return True, f"Đã kích hoạt PRO đến {user.pro_expires_at:%d-%m-%Y %H:%M} UTC."

def start_trial(tg_user_id:int, username:str|None):
    db = SessionLocal()
    tr = db.execute(select(Trial).where(Trial.user_id==tg_user_id)).scalar_one_or_none()
    if tr:
        return False, "Bạn đã dùng thử 1 lần rồi."
    user = db.get(User, tg_user_id) or User(id=tg_user_id, username=username)
    now = datetime.utcnow()
    exp = now + timedelta(days=TRIAL_DAYS)
    tr = Trial(user_id=tg_user_id, started_at=now, expires_at=exp, active=True)
    user.is_pro = True
    user.pro_expires_at = exp
    db.add_all([tr, user]); db.commit()
    return True, f"Dùng thử {TRIAL_DAYS} ngày. Hết hạn: {exp:%d-%m-%Y %H:%M} UTC."

def check_and_downgrade_expired():
    db = SessionLocal()
    now = datetime.utcnow()
    users = db.query(User).filter(User.is_pro==True, User.pro_expires_at < now).all()
    for u in users:
        u.is_pro = False
    trials = db.query(Trial).filter(Trial.active==True, Trial.expires_at < now).all()
    for t in trials:
        t.active = False
    db.commit()
    return len(users)
