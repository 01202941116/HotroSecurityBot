# keep_alive_server.py
from flask import Flask
from threading import Thread
import os

# Nếu bạn muốn dùng waitress production server:
try:
    from waitress import serve
    USE_WAITRESS = True
except Exception:
    USE_WAITRESS = False

app = Flask(__name__)

@app.route("/")
def home():
    return "✅ HotroSecurityBot is running!"

def run():
    port = int(os.getenv("PORT", "8080"))  # Render cấp PORT qua biến môi trường
    if USE_WAITRESS:
        # chạy bằng waitress để ổn định hơn
        serve(app, host="0.0.0.0", port=port)
    else:
        # fallback: Flask dev server (vẫn đọc PORT của Render)
        app.run(host="0.0.0.0", port=port, debug=False)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
