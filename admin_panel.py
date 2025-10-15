# admin_panel.py
# Simplified admin panel for HotroSecurityBot
# Installation:
# 1. Put this file into your project root (same level as main.py)
# 2. In keep_alive_server.py, add:
#       from admin_panel import admin_bp, init_admin_panel
#       init_admin_panel()
#       app.register_blueprint(admin_bp, url_prefix="/admin")
# 3. On Render, add environment variable ADMIN_PASSWORD
# 4. Access via: https://your-app.onrender.com/admin
import os
from flask import Blueprint, request, redirect, url_for, render_template_string, session
from sqlalchemy import func
from functools import wraps
try:
    from core.models import SessionLocal, User, LicenseKey, Whitelist, Filter
except:
    raise ImportError("⚠️ Cannot import core.models. Make sure project structure matches your bot.")

admin_bp = Blueprint("admin", __name__)
_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
_SESSION_KEY = os.getenv("ADMIN_SECRET", os.getenv("BOT_TOKEN", "secret"))

def init_admin_panel():
    try:
        import keep_alive_server as kas
        if getattr(kas, "app", None):
            kas.app.secret_key = _SESSION_KEY
    except Exception as e:
        print("[admin_panel] init error:", e)

def _require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin.login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

def _layout(title, body):
    return render_template_string(f"""<!DOCTYPE html>
    <html><head><meta charset='utf-8'><title>{title}</title>
    <style>body{{background:#0f172a;color:#fff;font-family:sans-serif;padding:20px}}
    a{{color:#4ade80}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #333;padding:6px}}</style></head>
    <body><h2>{title}</h2><p><a href='/admin'>🏠 Dashboard</a> | <a href='/admin/logout'>🚪 Logout</a></p>{body}</body></html>""")

@admin_bp.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == _ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect("/admin")
    return _layout("Login", "<form method='post'><input name='password' type='password' placeholder='Password'><button>Login</button></form>")

@admin_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/admin/login")

@admin_bp.route("/")
@_require_login
def dashboard():
    db = SessionLocal()
    users = db.query(func.count(User.id)).scalar() or 0
    keys = db.query(func.count(LicenseKey.id)).scalar() or 0
    wl = db.query(func.count(Whitelist.id)).scalar() or 0
    flt = db.query(func.count(Filter.id)).scalar() or 0
    db.close()
    return _layout("Dashboard", f"<ul><li>👤 Users: {users}</li><li>🔑 Keys: {keys}</li><li>✅ Whitelist: {wl}</li><li>🚫 Filters: {flt}</li></ul>")
