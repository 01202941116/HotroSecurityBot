# keep_alive_server.py
from flask import Flask
from threading import Thread
import os

try:
    from waitress import serve
    USE_WAITRESS = True
except Exception:
    USE_WAITRESS = False

app = Flask(__name__)

# --- Admin Panel ---
from admin_panel import admin_bp, init_admin_panel
init_admin_panel()
app.register_blueprint(admin_bp, url_prefix="/admin")
# -------------------

@app.route("/")
def home():
    return "✅ HotroSecurityBot is running!"

def _run():
    port = int(os.getenv("PORT", "8080"))
    if USE_WAITRESS:
        serve(app, host="0.0.0.0", port=port)   # production server
    else:
        app.run(host="0.0.0.0", port=port, debug=False)

def keep_alive():
    t = Thread(target=_run, daemon=True)
    t.start()
