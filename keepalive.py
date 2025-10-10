# keepalive.py  (no third-party deps)
from flask import Flask
from threading import Thread
import urllib.request
import time
import os

app = Flask(__name__)

@app.route("/")
def home():
    return "OK", 200

def run():
    # Render free chỉ cần mở 1 web server để ngăn sleep
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))

def ping(url: str):
    while True:
        try:
            # gọi nhẹ để đánh thức instance
            with urllib.request.urlopen(url, timeout=10) as _:
                pass
        except Exception:
            pass
        time.sleep(300)  # 5 phút gọi 1 lần

def start_keepalive():
    # URL public của service hiển thị trong log (Available at your primary URL)
    public_url = os.getenv("PUBLIC_URL", "https://hotrosecuritybot.onrender.com")
    Thread(target=run, daemon=True).start()
    Thread(target=ping, args=(public_url,), daemon=True).start()
