import os
from flask import Flask

app = Flask(__name__)

@app.get("/")
def index():
    return "ok", 200

def run():
    port = int(os.environ.get("PORT", 10000))  # Render cấp PORT
    app.run(host="0.0.0.0", port=port, threaded=True)
