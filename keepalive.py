# keepalive.py
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.get("/")
def index():
    return "ok", 200

def run():
    app.run(host="0.0.0.0", port=10000, debug=False)
