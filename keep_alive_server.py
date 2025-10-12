# keep_alive_server.py
import os
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!"

@app.route("/healthz")
def healthz():
    return "ok", 200

def _run():
    # Render sẽ đặt PORT vào biến môi trường, nếu không có thì dùng 8080
    port = int(os.getenv("PORT", "8080"))
    # debug=False để tránh log quá nhiều; threaded=True cho phép xử lý đồng thời
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

def keep_alive():
    # Daemon để thread webserver tự tắt theo tiến trình chính
    t = Thread(target=_run, daemon=True)
    t.start()
