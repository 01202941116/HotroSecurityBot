
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker
import os

DB_URL = os.getenv("LICENSE_DB_URL", "sqlite:///licenses.db")
engine = create_engine(DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)              # tg user id
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
    chat_id = Column(Integer, index=True)
    pattern = Column(String, index=True)

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, unique=True, index=True)
    antilink = Column(Boolean, default=False)
    flood_limit = Column(Integer, default=3)
    flood_mode = Column(String, default="mute")  # mute/none

def init_db():
    Base.metadata.create_all(engine)
