# keep_alive_server.py
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ HotroSecurityBot is running!"

def run():
    # Đặt debug=False, host 0.0.0.0 để Render không chặn
    app.run(host='0.0.0.0', port=8080, debug=False)

def keep_alive():
    # Chạy Flask trên luồng riêng, không chặn bot chính
    t = Thread(target=run)
    t.daemon = True  # đảm bảo thread tự đóng khi main process dừng
    t.start()
