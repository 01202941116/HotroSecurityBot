# core/models.py
from datetime import datetime, timedelta
import os

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey,
    BigInteger, func, inspect, text, Text   # <-- THÊM Text
)
from sqlalchemy.orm import declarative_base, sessionmaker

# ===== DB CONFIG =====
DB_URL = os.getenv("LICENSE_DB_URL", "sqlite:///licenses.db")

engine = create_engine(DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
Base = declarative_base()


# ====== UTILS ======
def now_utc():
    """
    Datetime UTC dạng NAIVE (không timezone info).
    Tránh lỗi: "can't compare offset-naive and offset-aware datetimes".
    """
    return datetime.utcnow()

def add_days(d: int):
    return now_utc() + timedelta(days=d)


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
    created_at = Column(DateTime, default=now_utc)

class Trial(Base):
    __tablename__ = "trials"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
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

# ==== Auto Promo (đồng bộ với main.py/scheduler.py) ====
class PromoSetting(Base):
    __tablename__ = "promo_settings"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, index=True, nullable=False)

    # Field mới (đồng nhất với code)
    is_enabled = Column(Boolean, default=False)
    content = Column(Text, default="")
    interval_minutes = Column(Integer, default=60)

    # Dùng NAIVE timestamp để khớp now_utc()
    last_sent_at = Column(DateTime, nullable=True, default=None)

    # Ghi chú: nếu DB cũ còn cột legacy (enabled/text/interval_min),
    # init_db() sẽ thêm cột mới và copy dữ liệu sang.


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


# ===== INIT / MIGRATION =====
def init_db():
    """Tạo bảng và tự migrate nhẹ cho promo_settings."""
    Base.metadata.create_all(bind=engine)

    try:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("promo_settings")}

        # Thêm cột mới nếu còn thiếu
        with engine.begin() as conn:
            if "is_enabled" not in cols:
                conn.execute(text(
                    "ALTER TABLE promo_settings ADD COLUMN is_enabled BOOLEAN DEFAULT 0"
                ))
            if "content" not in cols:
                conn.execute(text(
                    "ALTER TABLE promo_settings ADD COLUMN content TEXT DEFAULT ''"
                ))
            if "interval_minutes" not in cols:
                conn.execute(text(
                    "ALTER TABLE promo_settings ADD COLUMN interval_minutes INTEGER DEFAULT 60"
                ))
            if "last_sent_at" not in cols:
                conn.execute(text(
                    "ALTER TABLE promo_settings ADD COLUMN last_sent_at TIMESTAMP NULL"
                ))

            # Copy dữ liệu từ cột legacy (nếu tồn tại)
            # (re-inspect để chắc chắn có cột vừa thêm)
            cols = {c["name"] for c in inspect(engine).get_columns("promo_settings")}
            if "enabled" in cols and "is_enabled" in cols:
                conn.execute(text(
                    "UPDATE promo_settings SET is_enabled = COALESCE(is_enabled, enabled)"
                ))
            if "text" in cols and "content" in cols:
                conn.execute(text(
                    "UPDATE promo_settings SET content = COALESCE(NULLIF(content, ''), text)"
                ))
            if "interval_min" in cols and "interval_minutes" in cols:
                conn.execute(text(
                    "UPDATE promo_settings SET interval_minutes = COALESCE(interval_minutes, interval_min)"
                ))

    except Exception as e:
        # Không để crash nếu DB không hỗ trợ ALTER TABLE
        print("[migrate] promo_settings migration note:", e)


# ===== HELPERS =====
def count_users(session=None) -> int:
    """Đếm tổng số người dùng (User) trong CSDL."""
    s = session or SessionLocal()
    try:
        return s.query(User).count()
    finally:
        if session is None:
            s.close()
# --- Support mode (per-group) ---
from sqlalchemy import Boolean, Column, Integer, BigInteger, String, UniqueConstraint

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
    note = Column(String(120), default="")  # optional
    __table_args__ = (UniqueConstraint('chat_id', 'user_id', name='uix_supporter_chat_user'),)

def get_support_enabled(db: SessionLocal, chat_id: int) -> bool:
    s = db.query(SupportSetting).filter_by(chat_id=chat_id).one_or_none()
    return bool(s and s.is_enabled)

def list_supporters(db: SessionLocal, chat_id: int) -> list[int]:
    return [r.user_id for r in db.query(Supporter).filter_by(chat_id=chat_id).all()]
