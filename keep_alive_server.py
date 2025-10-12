# keep_alive_server.py
from flask import Flask
from threading import Thread
from waitress import serve  # thêm dòng này

app = Flask(__name__)

@app.route("/")
def home():
    return "✅ HotroSecurityBot is running!"

def _run():
    # chạy với waitress thay cho flask run()
    serve(app, host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=_run, daemon=True)
    t.start()
