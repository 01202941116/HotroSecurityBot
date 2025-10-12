# keep_alive_server.py
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return "✅ HotroSecurityBot is running!"

def _run():
    # Lắng nghe trên 0.0.0.0:8080 để Render/uptime robot ping được
    # Không bật debug để tránh log thừa & tự reload
    app.run(host="0.0.0.0", port=8080, debug=False)

def keep_alive():
    # Chạy Flask ở luồng nền; tự thoát khi tiến trình chính dừng
    t = Thread(target=_run, daemon=True)
    t.start()
