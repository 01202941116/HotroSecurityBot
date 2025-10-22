# admin_panel.py
from datetime import datetime, timedelta
import os
from flask import Blueprint, request, redirect, url_for, Response, session

from core.models import SessionLocal, User, LicenseKey

# ===== Blueprint cho trang /admin =====
admin_bp = Blueprint("admin", __name__)

# ===== Auth tuỳ chọn =====
# 1) Dùng ?token=... (giữ nguyên cách cũ nếu muốn)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
# 2) Đăng nhập username/password (mặc định theo yêu cầu, có thể đặt qua ENV)
ADMIN_USER = os.getenv("ADMIN_USER", "Myyduyenng").strip()
ADMIN_PASS = os.getenv("ADMIN_PASS", "12061991").strip()

def _is_logged_in() -> bool:
    return bool(session.get("admin_ok"))

def _login_nav() -> str:
    if _is_logged_in():
        return f'<span style="float:right;"><a href="{url_for("admin.logout")}">Logout</a></span>'
    return f'<span style="float:right;"><a href="{url_for("admin.login")}">Login</a></span>'

def _require_admin(req) -> bool:
    """
    Cho phép 2 cơ chế:
    - Nếu đã đăng nhập session -> OK
    - Hoặc nếu có ADMIN_TOKEN và query ?token=... khớp -> OK
    - Nếu không đặt ADMIN_TOKEN thì KHÔNG cần token (nhưng vẫn có thể yêu cầu đăng nhập).
    """
    if _is_logged_in():
        return True
    if ADMIN_TOKEN and req.args.get("token") == ADMIN_TOKEN:
        return True
    # Không có token thì bắt buộc đăng nhập
    return False


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
        input[type=text], input[type=password], input[type=number] {{
          padding:6px 10px; border-radius:4px; border:1px solid #2b415b; background:#142030; color:#fff;
        }}
        button {{ padding:6px 10px; }}
        .card {{ background:#111a2b; border:1px solid #2b415b; padding:16px; border-radius:8px; max-width:480px; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="nav">
          <a href="{url_for('admin.dashboard')}">🏠 Dashboard</a>
          <a href="{url_for('admin.users')}">👥 Users</a>
          <a href="{url_for('admin.keys')}">🔑 Keys</a>
          {_login_nav()}
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
        mins = (delta.seconds % 3600) // 60
        return f"{sign}{mins}m"
    return f"{sign}{days}d {hours}h"


def _is_trial(db, u: User) -> bool:
    try:
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
    if u.is_pro and u.pro_expires_at:
        return (u.pro_expires_at - datetime.utcnow()) <= timedelta(days=7)
    return False


def _trial_badge(is_trial: bool) -> str:
    if not is_trial:
        return ""
    return (
        '<span style="margin-left:6px;padding:2px 6px;'
        'border-radius:6px;background:#2a3b55;color:#ffd38a;'
        'font-size:12px;">TRIAL</span>'
    )


# ===== Login / Logout =====
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    # Nếu đã đăng nhập rồi -> về Users
    if _is_logged_in():
        return redirect(url_for("admin.users"))
    msg = ""
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = (request.form.get("password") or "").strip()
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["admin_ok"] = True
            return redirect(url_for("admin.users"))
        msg = "<p style='color:#ffb3b3;'>Sai username hoặc password.</p>"

    form = f"""
    <h2>Admin Login</h2>
    <div class="card">
      <form method="post">
        <div style="margin-bottom:10px;">
          <div>Username</div>
          <input type="text" name="username" placeholder="Username" value="{ADMIN_USER if os.getenv('ADMIN_USER') else ''}"/>
        </div>
        <div style="margin-bottom:10px;">
          <div>Password</div>
          <input type="password" name="password" placeholder="Password"/>
        </div>
        <button type="submit">Login</button>
      </form>
      {msg}
      <p style="opacity:.7;margin-top:10px;">Bạn có thể đặt ENV <code>ADMIN_USER</code>, <code>ADMIN_PASS</code> và <code>SECRET_KEY</code>.</p>
    </div>
    """
    return _html("Admin Login", form)

@admin_bp.route("/logout")
def logout():
    session.pop("admin_ok", None)
    return redirect(url_for("admin.login"))


# ===== Dashboard =====
@admin_bp.route("/")
def dashboard():
    if not _require_admin(request):
        return redirect(url_for("admin.login"))
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


# ===== Users + Search + Pagination =====
@admin_bp.route("/users")
def users():
    if not _require_admin(request):
        return redirect(url_for("admin.login"))

    db = SessionLocal()
    try:
        q = (request.args.get("q") or "").strip()
        page = max(1, int(request.args.get("page", 1)))
        per_page = 20

        query = db.query(User)
        if q:
            if q.isdigit():
                query = query.filter((User.id == int(q)) | (User.username.ilike(f"%{q}%")))
            else:
                query = query.filter(User.username.ilike(f"%{q}%"))

        total = query.count()
        pages = (total + per_page - 1) // per_page
        rows = query.order_by(User.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

        search_html = f"""
        <form method="get" style="margin-bottom:10px;">
          <input type="text" name="q" value="{q}" placeholder="🔍 Search username or ID..."/>
          <button type="submit">Search</button>
          {'<a href="' + url_for('admin.users') + '">Clear</a>' if q else ''}
        </form>
        """

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

        pag_html = ""
        if pages > 1:
            pag_html += '<div style="margin-top:10px;">'
            if page > 1:
                pag_html += f'<a href="{url_for("admin.users", q=q, page=page-1)}">⬅ Prev</a> '
            for p in range(1, pages + 1):
                if p == page:
                    pag_html += f"<b>[{p}]</b> "
                elif abs(p - page) <= 2 or p in (1, pages):
                    pag_html += f'<a href="{url_for("admin.users", q=q, page=p)}">{p}</a> '
                elif abs(p - page) == 3:
                    pag_html += "... "
            if page < pages:
                pag_html += f'<a href="{url_for("admin.users", q=q, page=page+1)}">Next ➡</a>'
            pag_html += "</div>"

        body = f"""
        <h2>Users</h2>
        {search_html}
        <table>
          <tr>
            <th>User ID</th><th>Username</th><th>TIER</th><th>Expires</th><th>Actions</th>
          </tr>
          {''.join(trs) or '<tr><td colspan="5">Empty</td></tr>'}
        </table>
        {pag_html}
        """
        return _html("Admin - Users", body)
    finally:
        db.close()


@admin_bp.route("/extend_user")
def extend_user():
    if not _require_admin(request):
        return redirect(url_for("admin.login"))
    uid = int(request.args.get("user_id", "0"))
    days = int(request.args.get("days", "30"))
    db = SessionLocal()
    try:
        u = db.get(User, uid)
        if not u:
            return _html(
                "Extend",
                f"<p>User {uid} not found.</p><p><a href='{url_for('admin.users')}'>Back</a></p>",
            )
        now = datetime.utcnow()
        if not u.pro_expires_at or u.pro_expires_at < now:
            u.pro_expires_at = now + timedelta(days=days)
        else:
            u.pro_expires_at = u.pro_expires_at + timedelta(days=days)
        u.is_pro = True
        db.commit()
        return redirect(url_for("admin.users"))
    finally:
        db.close()


@admin_bp.route("/set_free")
def set_free():
    if not _require_admin(request):
        return redirect(url_for("admin.login"))
    uid = int(request.args.get("user_id", "0"))
    db = SessionLocal()
    try:
        u = db.get(User, uid)
        if u:
            u.is_pro = False
            u.pro_expires_at = None
            db.commit()
        return redirect(url_for("admin.users"))
    finally:
        db.close()


# ===== Keys + Create / Delete =====
@admin_bp.route("/keys")
def keys():
    if not _require_admin(request):
        return redirect(url_for("admin.login"))
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
        return redirect(url_for("admin.login"))
    import secrets

    days = max(1, int(request.form.get("days", "30")))
    tier = (request.form.get("tier", "pro") or "pro").strip()

    db = SessionLocal()
    try:
        key = f"KEY-{secrets.token_urlsafe(12)}"
        db.add(LicenseKey(key=key, tier=tier, days=days))
        db.commit()
        return redirect(url_for("admin.keys"))
    finally:
        db.close()


@admin_bp.route("/keys/delete")
def delete_key():
    if not _require_admin(request):
        return redirect(url_for("admin.login"))
    key_id = int(request.args.get("key_id", "0"))
    db = SessionLocal()
    try:
        k = db.get(LicenseKey, key_id)
        if k:
            db.delete(k)
            db.commit()
        return redirect(url_for("admin.keys"))
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
        # cần SECRET_KEY cho Flask session
        if not getattr(app, "secret_key", None):
            app.secret_key = os.getenv("SECRET_KEY", "change-me-please")
        app.register_blueprint(admin_bp, url_prefix="/admin")
    return admin_bp
