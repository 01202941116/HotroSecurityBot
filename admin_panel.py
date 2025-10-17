# admin_panel.py
from datetime import datetime, timedelta
import os
from flask import Blueprint, request, redirect, url_for, Response

from core.models import SessionLocal, User, LicenseKey

# ===== Blueprint cho trang /admin =====
admin_bp = Blueprint("admin", __name__)

# ===== Auth rất nhẹ (tuỳ chọn) =====
# Đặt biến môi trường ADMIN_TOKEN (Render -> Environment) để bắt buộc ?token=...
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

def _require_admin(req) -> bool:
    """Nếu có ADMIN_TOKEN thì bắt buộc query '?token=...'; ngược lại mở tự do (cho test)."""
    if not ADMIN_TOKEN:
        return True
    return req.args.get("token") == ADMIN_TOKEN

def _html(title: str, body: str) -> Response:
    html = f"""
    <html>
    <head>
      <meta charset="utf-8"/>
      <title>{title}</title>
      <style>
        body {{ background:#0f1624; color:#cde3ff; font-family: Arial, sans-serif; }}
        a {{ color:#9bd3ff; text-decoration:none; }}
        table {{ border-collapse: collapse; width:100%; max-width:1080px; }}
        th, td {{ border:1px solid #2b415b; padding:8px; }}
        th {{ background:#152235; }}
        .wrap {{ max-width:1080px; margin:24px auto; }}
        .nav a {{ margin-right:12px; }}
        .btn {{ margin-right:6px; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="nav">
          <a href="{url_for('admin.dashboard')}">🏠 Dashboard</a>
          <a href="{url_for('admin.users')}">👥 Users</a>
          <a href="{url_for('admin.keys')}">🔑 Keys</a>
        </div>
        {body}
      </div>
    </body>
    </html>
    """
    return Response(html)

def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")

def _human_left(expires_at: datetime | None) -> str:
def _is_trial(db, u: User) -> bool:
    """Xác định user có đang dùng thử không.
    Ưu tiên theo key (issued_to == user.id và days <= 7), fallback theo thời gian còn lại."""
    try:
        # issued_to lưu chuỗi; một số DB bạn lưu user_id dạng str
        uid_str = str(u.id)
        k = (
            db.query(LicenseKey)
              .filter(LicenseKey.issued_to == uid_str)
              .order_by(LicenseKey.id.desc())
              .first()
        )
        if k and k.days and k.days <= 7:
            return True
    except Exception:
        pass

    # Fallback: còn lại <= 7 ngày
    if u.is_pro and u.pro_expires_at:
        return (u.pro_expires_at - datetime.utcnow()) <= timedelta(days=7)
    return False


def _trial_badge(is_trial: bool) -> str:
    if not is_trial:
        return ""
    return '<span style="margin-left:6px;padding:2px 6px;border-radius:6px;background:#2a3b55;color:#ffd38a;font-size:12px;">TRIAL</span>'
    """
    Hiển thị thời gian còn lại/đã hết hạn dạng '5d 12h' hoặc 'expired 3d 2h'.
    Không ảnh hưởng tới logic hết hạn thật trong DB.
    """
    if not expires_at:
        return "0d"
    delta = expires_at - datetime.utcnow()
    sign = ""
    if delta.total_seconds() <= 0:
        delta = -delta
        sign = "expired "

    days = delta.days
    hours = delta.seconds // 3600
    if days == 0 and hours == 0:
        # < 1h
        mins = (delta.seconds % 3600) // 60
        return f"{sign}{mins}m"
    return f"{sign}{days}d {hours}h"

# ===== Dashboard =====
@admin_bp.route("/")
def dashboard():
    if not _require_admin(request):
        return _html("Forbidden", "<h3>Forbidden (missing ?token)</h3>")
    db = SessionLocal()
    try:
        users = db.query(User).count()
        keys = db.query(LicenseKey).count()
        body = f"""
        <h1>Dashboard</h1>
        <ul>
          <li>Users: <b>{users}</b></li>
          <li>Keys: <b>{keys}</b></li>
        </ul>
        """
        return _html("Admin Dashboard", body)
    finally:
        db.close()

# ===== Users + Extend / Set FREE =====
@admin_bp.route("/users")
def users():
    if not _require_admin(request):
        return _html("Forbidden", "<h3>Forbidden (missing ?token)</h3>")
    db = SessionLocal()
    try:
        rows = db.query(User).order_by(User.id.desc()).limit(200).all()
        trs = []
        for u in rows:
    tier = "PRO" if u.is_pro else "FREE"
    expires = _fmt_dt(u.pro_expires_at)
    left_human = _human_left(u.pro_expires_at)
    trial = _is_trial(db, u)
    badge = _trial_badge(trial)

    trs.append(f"""
    <tr>
      <td>{u.id}</td>
      <td>{u.username or ''}</td>
      <td>{tier}{badge}</td>
      <td>{expires} (left: {left_human})</td>
      <td>
        <a class="btn" href="{url_for('admin.extend_user', user_id=u.id, days=30)}">+30d</a>
        <a class="btn" href="{url_for('admin.extend_user', user_id=u.id, days=90)}">+90d</a>
        <a class="btn" href="{url_for('admin.extend_user', user_id=u.id, days=365)}">+365d</a>
        <a class="btn" href="{url_for('admin.set_free', user_id=u.id)}">Set FREE</a>
      </td>
    </tr>
    """)
        body = f"""
        <h2>Users</h2>
        <table>
          <tr>
            <th>User ID</th><th>Username</th><th>TIER</th><th>Expires</th><th>Actions</th>
          </tr>
          {''.join(trs) or '<tr><td colspan="5">Empty</td></tr>'}
        </table>
        """
        return _html("Admin - Users", body)
    finally:
        db.close()

@admin_bp.route("/extend_user")
def extend_user():
    if not _require_admin(request):
        return _html("Forbidden", "<h3>Forbidden (missing ?token)</h3>")
    uid = int(request.args.get("user_id", "0"))
    days = int(request.args.get("days", "30"))
    db = SessionLocal()
    try:
        u = db.get(User, uid)
        if not u:
            return _html("Extend", f"<p>User {uid} not found.</p><p><a href='{url_for('admin.users')}'>Back</a></p>")
        now = datetime.utcnow()
        if not u.pro_expires_at or u.pro_expires_at < now:
            u.pro_expires_at = now + timedelta(days=days)
        else:
            u.pro_expires_at = u.pro_expires_at + timedelta(days=days)
        u.is_pro = True
        db.commit()
        return redirect(url_for('admin.users'))
    finally:
        db.close()

@admin_bp.route("/set_free")
def set_free():
    if not _require_admin(request):
        return _html("Forbidden", "<h3>Forbidden (missing ?token)</h3>")
    uid = int(request.args.get("user_id", "0"))
    db = SessionLocal()
    try:
        u = db.get(User, uid)
        if u:
            u.is_pro = False
            u.pro_expires_at = None
            db.commit()
        return redirect(url_for('admin.users'))
    finally:
        db.close()

# ===== Keys + Create / Delete =====
@admin_bp.route("/keys")
def keys():
    if not _require_admin(request):
        return _html("Forbidden", "<h3>Forbidden (missing ?token)</h3>")
    db = SessionLocal()
    try:
        rows = db.query(LicenseKey).order_by(LicenseKey.id.desc()).limit(200).all()
        trs = []
        for k in rows:
            status = "USED" if k.used else "NEW"
            trs.append(f"""
            <tr>
              <td>{k.id}</td>
              <td>{k.key}</td>
              <td>{k.tier}</td>
              <td>{k.days}d</td>
              <td>{k.issued_to or ''}</td>
              <td>{status}</td>
              <td><a class="btn" href="{url_for('admin.delete_key', key_id=k.id)}">Delete</a></td>
            </tr>
            """)
        form = f"""
        <form method="post" action="{url_for('admin.create_key')}">
          <h3>Create key</h3>
          Days: <input type="number" name="days" value="30" style="width:80px" />
          Tier: <input type="text" name="tier" value="pro" style="width:100px" />
          <button type="submit">Create</button>
        </form>
        """
        body = f"""
        <h2>Keys</h2>
        {form}
        <br/>
        <table>
          <tr>
            <th>ID</th><th>Key</th><th>Tier</th><th>Days</th><th>IssuedTo</th><th>Status</th><th>Actions</th>
          </tr>
          {''.join(trs) or '<tr><td colspan="7">Empty</td></tr>'}
        </table>
        """
        return _html("Admin - Keys", body)
    finally:
        db.close()

@admin_bp.route("/keys/create", methods=["POST"])
def create_key():
    if not _require_admin(request):
        return _html("Forbidden", "<h3>Forbidden (missing ?token)</h3>")
    import secrets
    days = max(1, int(request.form.get("days", "30")))
    tier = (request.form.get("tier", "pro") or "pro").strip()

    db = SessionLocal()
    try:
        key = f"KEY-{secrets.token_urlsafe(12)}"
        db.add(LicenseKey(key=key, tier=tier, days=days))
        db.commit()
        return redirect(url_for('admin.keys'))
    finally:
        db.close()

@admin_bp.route("/keys/delete")
def delete_key():
    if not _require_admin(request):
        return _html("Forbidden", "<h3>Forbidden (missing ?token)</h3>")
    key_id = int(request.args.get("key_id", "0"))
    db = SessionLocal()
    try:
        k = db.get(LicenseKey, key_id)
        if k:
            db.delete(k)
            db.commit()
        return redirect(url_for('admin.keys'))
    finally:
        db.close()

# ===== helper để gọi từ keep_alive_server hoặc main =====
def init_admin_panel(app=None):
    """
    Tuỳ chọn:
    - init_admin_panel(app): đăng ký ngay vào app
    - hoặc chỉ import admin_bp và tự app.register_blueprint(admin_bp, url_prefix='/admin')
    """
    if app is not None:
        app.register_blueprint(admin_bp, url_prefix="/admin")
    return admin_bp
