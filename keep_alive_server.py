# keep_alive_server.py
from flask import Flask
from threading import Thread

# Tạo Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

# Chạy webserver để Render giữ bot online
def run():
    app.run(host='0.0.0.0', port=8080)

# Hàm gọi song song, giúp bot không bị sleep
def keep_alive():
    t = Thread(target=run)
    t.start()
