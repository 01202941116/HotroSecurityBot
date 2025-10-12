# core/models.py
from datetime import datetime, timedelta
import os

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey,
    BigInteger, func
)
from sqlalchemy.orm import declarative_base, sessionmaker

# ===== DB CONFIG =====
DB_URL = os.getenv("LICENSE_DB_URL", "sqlite:///licenses.db")

engine = create_engine(DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
Base = declarative_base()

# ===== ENTITIES =====

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)           # telegram user id
    username = Column(String, nullable=True)
    is_pro = Column(Boolean, default=False)
    pro_expires_at = Column(DateTime, nullable=True)

class LicenseKey(Base):
    __tablename__ = "license_keys"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True)
    tier = Column(String, default="pro")
    days = Column(Integer, default=30)
    issued_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Trial(Base):
    __tablename__ = "trials"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    active = Column(Boolean, default=True)

class Filter(Base):
    __tablename__ = "filters"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    pattern = Column(String, index=True)

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True)
    antilink = Column(Boolean, default=True)
    antimention = Column(Boolean, default=True)
    antiforward = Column(Boolean, default=True)
    flood_limit = Column(Integer, default=3)
    flood_mode = Column(String, default="mute")

class Whitelist(Base):
    __tablename__ = "whitelist"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    domain = Column(String, index=True)

class Captcha(Base):
    __tablename__ = "captcha"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    user_id = Column(BigInteger, index=True)
    answer = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

# ==== Auto Promo ====
class PromoSetting(Base):
    __tablename__ = "promo_settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True)
    enabled = Column(Boolean, default=False)
    text = Column(String, default="🎯 Tham gia gói PRO để mở khoá đầy đủ tính năng!")
    interval_min = Column(Integer, default=360)  # 6 giờ

# ===== Warning & Blacklist =====
class Warning(Base):
    __tablename__ = "warnings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)   # dùng BigInteger cho id Telegram
    user_id = Column(BigInteger, index=True)
    count = Column(Integer, default=0)
    last_warned = Column(DateTime, default=func.now())

class Blacklist(Base):
    __tablename__ = "blacklists"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    user_id = Column(BigInteger, index=True)
    created_at = Column(DateTime, default=func.now())

# ===== UTILS =====

def init_db():
    Base.metadata.create_all(engine)

def now_utc():
    return datetime.utcnow()

def add_days(d: int):
    return now_utc() + timedelta(days=d)

def count_users(session=None) -> int:
    """Đếm tổng số người dùng (User) trong CSDL."""
    s = session or SessionLocal()
    try:
        return s.query(User).count()
        # core/models.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, BigInteger, Boolean, Text, DateTime
# ... các import khác ...

def now_utc():
    return datetime.now(timezone.utc)

class PromoSetting(Base):
    __tablename__ = "promo_settings"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True, nullable=False)

    is_enabled = Column(Boolean, default=False)        # /ad_on | /ad_off
    content = Column(Text, default="")                 # /ad_set <nội dung>
    interval_minutes = Column(Integer, default=60)     # /ad_interval <phút>

    # >>> THÊM CỘT NÀY <<<
    last_sent_at = Column(DateTime(timezone=True), nullable=True, default=None)

    finally:
        if session is None:
            s.close()
# core/models.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, BigInteger, Boolean, Text, DateTime
# ... các import/layer khác ...

def now_utc():
    return datetime.now(timezone.utc)

class PromoSetting(Base):
    __tablename__ = "promo_settings"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True, nullable=False)

    is_enabled = Column(Boolean, default=False)          # /ad_on | /ad_off
    content = Column(Text, default="")                   # /ad_set <nội dung>
    interval_minutes = Column(Integer, default=60)       # /ad_interval <phút>

    # >>> THÊM CỘT NÀY <<<
    last_sent_at = Column(DateTime(timezone=True), nullable=True, default=None)
