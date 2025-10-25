# core/models.py
from datetime import datetime, timedelta
import os

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey,
    BigInteger, func, inspect, text, Text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker

# ===== DB CONFIG =====
# Render: DATABASE_URL (postgresql), local fallback: SQLite
DB_URL = os.getenv("DATABASE_URL", os.getenv("LICENSE_DB_URL", "sqlite:///licenses.db"))

# Auto-fix postgres scheme
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

# Engine
connect_args = {}
if DB_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DB_URL, future=True, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
Base = declarative_base()

# ====== UTILS ======
def now_utc() -> datetime:
    """Datetime UTC (naive)."""
    return datetime.utcnow()

def add_days(d: int) -> datetime:
    return now_utc() + timedelta(days=d)

# ===== ENTITIES =====
class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)         # Telegram user id (64-bit)
    username = Column(String, nullable=True)
    is_pro = Column(Boolean, default=False)
    pro_expires_at = Column(DateTime, nullable=True)

class LicenseKey(Base):
    __tablename__ = "license_keys"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True)
    tier = Column(String, default="pro")
    days = Column(Integer, default=30)
    issued_to = Column(BigInteger, ForeignKey("users.id"), nullable=True)  # 64-bit
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_utc)

class Trial(Base):
    __tablename__ = "trials"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True)  # 64-bit
    started_at = Column(DateTime, default=now_utc)
    expires_at = Column(DateTime)
    active = Column(Boolean, default=True)

class Filter(Base):
    __tablename__ = "filters"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)  # 64-bit
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
    nobots = Column(Boolean, default=True)
    # ➕ Lời chào thành viên mới (FREE)
    welcome_text = Column(Text, nullable=True)

class Whitelist(Base):
    __tablename__ = "whitelist"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)  # 64-bit
    domain = Column(String, index=True)

class Captcha(Base):
    __tablename__ = "captcha"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)  # 64-bit
    user_id = Column(BigInteger, index=True)  # 64-bit
    answer = Column(String)
    created_at = Column(DateTime, default=now_utc)

# ==== Auto Promo ====
class PromoSetting(Base):
    __tablename__ = "promo_settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True, nullable=False)  # 64-bit
    is_enabled = Column(Boolean, default=False)
    content = Column(Text, default="")
    interval_minutes = Column(Integer, default=60)
    last_sent_at = Column(DateTime, nullable=True, default=None)

# ===== Warning & Blacklist =====
class Warning(Base):
    __tablename__ = "warnings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)  # 64-bit
    user_id = Column(BigInteger, index=True)  # 64-bit
    count = Column(Integer, default=0)
    last_warned = Column(DateTime, default=func.now())

class Blacklist(Base):
    __tablename__ = "blacklists"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)  # 64-bit
    user_id = Column(BigInteger, index=True)  # 64-bit
    created_at = Column(DateTime, default=func.now())

# --- Support mode (per-group) ---
class SupportSetting(Base):
    __tablename__ = "support_settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True, nullable=False, unique=True)  # 64-bit
    is_enabled = Column(Boolean, default=False)

class Supporter(Base):
    __tablename__ = "supporters"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True, nullable=False)   # 64-bit
    user_id = Column(BigInteger, index=True, nullable=False)   # 64-bit
    note = Column(String(120), default="")
    __table_args__ = (UniqueConstraint('chat_id', 'user_id', name='uix_supporter_chat_user'),)

# ===== INIT / MIGRATION =====
def init_db():
    """Tạo bảng và migrate nhẹ cho các cột mới."""
    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)

    # --- ensure promo_settings columns ---
    try:
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
        print("[migrate] promo_settings:", e)

    # --- ensure settings.nobots ---
    try:
        cols_settings = {c["name"] for c in insp.get_columns("settings")}
        with engine.begin() as conn:
            if "nobots" not in cols_settings:
                conn.execute(text("ALTER TABLE settings ADD COLUMN nobots BOOLEAN DEFAULT TRUE"))
                conn.execute(text("UPDATE settings SET nobots = TRUE WHERE nobots IS NULL"))
            # ➕ ensure settings.welcome_text
            if "welcome_text" not in cols_settings:
                conn.execute(text("ALTER TABLE settings ADD COLUMN welcome_text TEXT NULL"))
    except Exception as e:
        print("[migrate] settings:", e)

# ===== HELPERS =====
def count_users(session=None) -> int:
    s = session or SessionLocal()
    try:
        return s.query(User).count()
    finally:
        if session is None:
            s.close()

def get_support_enabled(db: SessionLocal, chat_id: int) -> bool:
    s = db.query(SupportSetting).filter_by(chat_id=chat_id).one_or_none()
    return bool(s and s.is_enabled)

def list_supporters(db: SessionLocal, chat_id: int) -> list[int]:
    return [r.user_id for r in db.query(Supporter).filter_by(chat_id=chat_id).all()]

# ===== Welcome message (DB-based, không dùng RAM) =====
def set_welcome_message(chat_id: int, text: str):
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
        if not s:
            s = Setting(chat_id=chat_id)
            db.add(s)
        s.welcome_text = (text or "").strip()
        db.commit()
    finally:
        db.close()

def get_welcome_message(chat_id: int) -> str | None:
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
        return (s.welcome_text or None) if s else None
    finally:
        db.close()

def get_support_enabled(db: SessionLocal, chat_id: int) -> bool:
    s = db.query(SupportSetting).filter_by(chat_id=chat_id).one_or_none()
    return bool(s and s.is_enabled)

def list_supporters(db: SessionLocal, chat_id: int) -> list[int]:
    return [r.user_id for r in db.query(Supporter).filter_by(chat_id=chat_id).all()]
    welcome_messages = {}

def set_welcome_message(chat_id: int, text: str):
    welcome_messages[chat_id] = text

def get_welcome_message(chat_id: int) -> str:
    return welcome_messages.get(chat_id)

