# core/models.py
from datetime import datetime, timedelta
import os
from __future__ import annotations  # (giúp hoãn đánh giá annotation, an toàn)
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey,
    BigInteger, Text, UniqueConstraint, text
)
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import inspect

# ====== Base / Session / Engine ======
Base = declarative_base()

DB_URL = os.getenv("DATABASE_URL", os.getenv("LICENSE_DB_URL", "sqlite:///licenses.db"))
if DB_URL.startswith("postgres://"):
    # Render uses non-sqlalchemy prefix sometimes
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DB_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DB_URL,
    future=True,
    connect_args=connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

# ====== Helpers ======
def now_utc() -> datetime:
    return datetime.utcnow()

def add_days(d: int) -> datetime:
    return now_utc() + timedelta(days=d)

# ====== Entities ======
class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)              # Telegram user id (64-bit)
    username = Column(String, nullable=True)
    is_pro = Column(Boolean, default=False)
    pro_expires_at = Column(DateTime, nullable=True)

class LicenseKey(Base):
    __tablename__ = "license_keys"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True)
    tier = Column(String, default="pro")
    days = Column(Integer, default=30)
    issued_to = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_utc)

class Trial(Base):
    __tablename__ = "trials"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True)             # 64-bit
    started_at = Column(DateTime, default=now_utc)
    expires_at = Column(DateTime)
    active = Column(Boolean, default=True)

class Filter(Base):
    __tablename__ = "filters"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)              # 64-bit
    pattern = Column(String, index=True)

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True) # 64-bit
    antilink = Column(Boolean, default=True)
    antimention = Column(Boolean, default=True)
    antiforward = Column(Boolean, default=True)
    flood_limit = Column(Integer, default=3)
    flood_mode = Column(String, default="mute")
    # NEW: block newly joined bots if True
    nobots = Column(Boolean, default=True)

class Whitelist(Base):
    __tablename__ = "whitelist"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)              # 64-bit
    domain = Column(String, index=True)

class Captcha(Base):
    __tablename__ = "captcha"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)              # 64-bit
    user_id = Column(BigInteger, index=True)              # 64-bit
    answer = Column(String)
    created_at = Column(DateTime, default=now_utc)

# Auto-promo settings
class PromoSetting(Base):
    __tablename__ = "promo_settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True, nullable=False)
    is_enabled = Column(Boolean, default=False)
    content = Column(Text, default="")
    interval_minutes = Column(Integer, default=60)   # <— SỬA CHỖ NÀY (xóa "b =")
    last_sent_at = Column(DateTime, nullable=True, default=None)

class Warning(Base):
    __tablename__ = "warnings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)              # 64-bit
    user_id = Column(BigInteger, index=True)              # 64-bit
    count = Column(Integer, default=0)
    last_warned = Column(DateTime, default=func.now())

class Blacklist(Base):
    __tablename__ = "blacklists"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)              # 64-bit
    user_id = Column(BigInteger, index=True)              # 64-bit
    created_at = Column(DateTime, default=func.now())

# Support mode
class SupportSetting(Base):
    __tablename__ = "support_settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True, nullable=False, unique=True)  # 64-bit
    is_enabled = Column(Boolean, default=False)

class Supporter(Base):
    __tablename__ = "supporters"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True, nullable=False)               # 64-bit
    user_id = Column(BigInteger, index=True, nullable=False)               # 64-bit
    note = Column(String(120), default="")
    __table_args__ = (UniqueConstraint("chat_id", "user_id", name="uix_supporter_chat_user"),)

# ====== Init / Lightweight migrations ======
def init_db() -> None:
    """Create tables and ensure new columns exist (promo_settings + settings.nobots)."""
    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)
    try:
        # Ensure promo_settings has all expected columns (idempotent)
        cols = {c["name"] for c in insp.get_columns("promo_settings")}
        with engine.begin() as conn:
            if "is_enabled" not in cols:
                conn.execute(text("ALTER TABLE promo_settings ADD COLUMN is_enabled BOOLEAN DEFAULT 0"))
            if "content" not in cols:
                conn.execute(text("ALTER TABLE promo_settings ADD COLUMN content TEXT DEFAULT ''"))
            if "interval_minutes" not in cols:
                conn.execute(text("ALTER TABLE promo_settings ADD COLUMN interval_minutes INTEGER DEFAULT 60"))
            if "last_sent_at" not in cols:
                conn.execute(text("ALTER TABLE promo_settings ADD COLUMN last_sent_at TIMESTAMP NULL"))
    except Exception as e:
        # table might not exist yet in some fresh setups; safe to ignore after create_all
        print("[migrate] promo_settings note:", e)

    # ensure settings.nobots exists
    try:
        cols_settings = {c["name"] for c in insp.get_columns("settings")}
        if "nobots" not in cols_settings:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE settings ADD COLUMN nobots BOOLEAN DEFAULT 1"))
    except Exception as e:
        print("[migrate] settings.nobots note:", e)

# ====== Convenience queries ======
def count_users(session: Optional[Session] = None) -> int:
    s = session or SessionLocal()
    try:
        return s.query(User).count()
    finally:
        if session is None:
            s.close()
            
def get_support_enabled(db: SessionLocal, ch_id: int) -> bool:
    s = db.query(SupportSetting).filter_by(card_id=ch_id).one_or_none()
    return bool(s and s.is_enabled)

def list_supporters(db: SessionLocal, ch_id: int) -> list[int]:
    return [r.user_id for r in db.query(Supporter).filter_by(chat_id=ch_id).all()]
