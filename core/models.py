# core/models.py
from datetime import datetime, timedelta
from typing import Optional
import os
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey,
    BigInteger, func, inspect, text, Text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker

# ===== DB CONFIG =====
DB_URL = os.getenv(
    "DATABASE_URL",
    os.getenv("LICENSE_DB_URL", "sqlite:///licenses.db")
)
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DB_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DB_URL, future=True, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
Base = declarative_base()

# ====== UTILS ======
def now_utc():
    return datetime.utcnow()

def add_days(d: int):
    return now_utc() + timedelta(days=d)

# ===== ENTITIES =====
class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)          # Telegram user id 64-bit
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
    user_id = Column(BigInteger, unique=True)
    started_at = Column(DateTime, default=now_utc)
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
    nobots = Column(Boolean, default=True)
    welcome_ttl = Column(Integer, default=900)  # giây; 0 = không auto-xoá
    antispam = Column(Boolean, default=True)
    welcome_text = Column(Text, nullable=True, default=None)
    
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
    created_at = Column(DateTime, default=now_utc)

# ==== Auto Promo ====
class PromoSetting(Base):
    __tablename__ = "promo_settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True, nullable=False)
    is_enabled = Column(Boolean, default=False)
    content = Column(Text, default="")
    interval_minutes = Column(Integer, default=60)
    last_sent_at = Column(DateTime, nullable=True, default=None)

# ===== Warning & Blacklist =====
class Warning(Base):
    __tablename__ = "warnings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    user_id = Column(BigInteger, index=True)
    count = Column(Integer, default=0)
    last_warned = Column(DateTime, default=func.now())

class Blacklist(Base):
    __tablename__ = "blacklists"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    user_id = Column(BigInteger, index=True)
    created_at = Column(DateTime, default=func.now())

# --- Support mode (per-group) ---
class SupportSetting(Base):
    __tablename__ = "support_settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True, nullable=False, unique=True)
    is_enabled = Column(Boolean, default=False)

class Supporter(Base):
    __tablename__ = "supporters"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    note = Column(String(120), default="")
    __table_args__ = (UniqueConstraint('chat_id', 'user_id', name='uix_supporter_chat_user'),)

# ===== Welcome message (RAM) =====
# LƯU Ý: phải đặt ở top-level (không bên trong hàm) để luôn tồn tại.
welcome_messages: dict[int, str] = {}

def set_welcome_message(chat_id: int, text: str):
    welcome_messages[chat_id] = text

def get_welcome_message(chat_id: int) -> str | None:
    return welcome_messages.get(chat_id)

# ===== INIT / MIGRATION =====
def init_db():
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)

    # ... (các migrate khác giữ nguyên)

    # ensure settings.nobots
    try:
        cols_settings = {c["name"] for c in insp.get_columns("settings")}
        if "nobots" not in cols_settings:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE settings ADD COLUMN nobots BOOLEAN DEFAULT TRUE"))
                conn.execute(text("UPDATE settings SET nobots = TRUE WHERE nobots IS NULL"))
    except Exception as e:
        print("[migrate] settings.nobots note:", e)

    # ensure settings.welcome_ttl
    try:
        cols_settings = {c["name"] for c in insp.get_columns("settings")}
        if "welcome_ttl" not in cols_settings:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE settings ADD COLUMN welcome_ttl INTEGER DEFAULT 900"))
    except Exception as e:
        print("[migrate] settings.welcome_ttl note:", e)

    # ensure settings.antispam
    try:
        cols_settings = {c["name"] for c in insp.get_columns("settings")}
        if "antispam" not in cols_settings:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE settings ADD COLUMN antispam BOOLEAN DEFAULT TRUE"))
                conn.execute(text("UPDATE settings SET antispam = TRUE WHERE antispam IS NULL"))
    except Exception as e:
        print("[migrate] settings.antispam note:", e)

    # ✅ ensure settings.welcome_text
    try:
        cols_settings = {c["name"] for c in insp.get_columns("settings")}
        if "welcome_text" not in cols_settings:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE settings ADD COLUMN welcome_text TEXT NULL"))
    except Exception as e:
        print("[migrate] settings.welcome_text note:", e)
    
    

# ===== HELPERS =====
def count_users(db_sess: Optional[SessionLocal] = None) -> int:
    s = db_sess or SessionLocal()
    try:
        return s.query(User).count()
    finally:
        if db_sess is None:
            s.close()

def get_support_enabled(db: SessionLocal, chat_id: int) -> bool:
    row = db.query(SupportSetting).filter_by(chat_id=chat_id).one_or_none()
    return bool(row and row.is_enabled)

def list_supporters(db: SessionLocal, chat_id: int) -> list[int]:
    return [r.user_id for r in db.query(Supporter).filter_by(chat_id=chat_id).all()]

# --- Welcome TTL ---
def get_welcome_ttl(chat_id: int) -> int:
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
        if not s:
            s = Setting(chat_id=chat_id, welcome_ttl=900)
            db.add(s); db.commit(); db.refresh(s)
        return int(getattr(s, "welcome_ttl", 900) or 0)
    finally:
        db.close()

def set_welcome_ttl(chat_id: int, seconds: int) -> int:
    secs = max(0, int(seconds))
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
        if not s:
            s = Setting(chat_id=chat_id)
            db.add(s); db.commit(); db.refresh(s)
        s.welcome_ttl = secs
        db.commit()
        return secs
    finally:
        db.close()

# --- Welcome text (lưu DB, không mất khi redeploy) ---
def set_welcome_message(chat_id: int, text: str) -> None:
    db = SessionLocal()
    try:
        s = db.query(Setting).filter_by(chat_id=chat_id).one_or_none()
        if not s:
            s = Setting(chat_id=chat_id)
            db.add(s)
        s.welcome_text = (text or "").strip() or None
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


    
