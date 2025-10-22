# admin_panel.py
from datetime import datetime, timedelta
import os
from flask import Blueprint, request, redirect, url_for, Response

from core.models import SessionLocal, User, LicenseKey

# ===== Blueprint cho trang /admin =====
admin_bp = Blueprint("admin", __name__)

# ===== Auth rất nhẹ (tuỳ chọn) =====
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()


def _require_admin(req) -> bool:
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
        input[type=text] {{ padding:4px 8px; border-radius:4px; border:1px solid #2b415b; background:#142030; color:#fff; }}
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


# ===== Users + Search + Pagination =====
@admin_bp.route("/users")
def users():
    if not _require_admin(request):
        return _html("Forbidden", "<h3>Forbidden (missing ?token)</h3>")

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

        # Search box
        search_html = f"""
        <form method="get" style="margin-bottom:10px;">
          <input type="text" name="q" value="{q}" placeholder="🔍 Search username or ID..."/>
          <button type="submit">Search</button>
          {'<a href="' + url_for('admin.users') + '">Clear</a>' if q else ''}
        </form>
        """

        # Table content
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

        # Pagination
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
