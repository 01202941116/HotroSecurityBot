# keep_alive_server.py
from flask import Flask
from threading import Thread
import os

try:
    from waitress import serve
    USE_WAITRESS = True
except Exception:
    USE_WAITRESS = False

# ====== Flask app ======
app = Flask(__name__)

# --- Admin Panel ---
try:
    from admin_panel import admin_bp, init_admin_panel
    # Truyền app để khởi tạo context an toàn
    init_admin_panel(app)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    print("✅ Admin panel loaded tại /admin")
except Exception as e:
    print(f"⚠️ Không thể load admin panel: {e}")
# -------------------

@app.route("/")
def home():
    return "✅ HotroSecurityBot is running!"

# ====== Run server ======
def _run():
    try:
        port = int(os.getenv("PORT", "8080"))  # Render sẽ tự cấp port động
        host = "0.0.0.0"
        if USE_WAITRESS:
            print(f"🌐 Serving on http://{host}:{port} (Waitress mode)")
            serve(app, host=host, port=port)
        else:
            print(f"🌐 Serving on http://{host}:{port} (Flask mode)")
            app.run(host=host, port=port, debug=False)
    except Exception as e:
        print(f"❌ Lỗi khi khởi động keep_alive server: {e}")

# ====== Keep alive thread ======
def keep_alive():
    """Chạy server nền để Render thấy service online"""
    t = Thread(target=_run, daemon=True)
    t.start()
