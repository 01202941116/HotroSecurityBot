# keepalive.py
import os
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "ok", 200

def run():
    # Render đặt PORT qua env, không hard-code cổng
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
