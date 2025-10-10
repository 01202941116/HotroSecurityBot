
from flask import Flask
import os

app = Flask(__name__)

@app.get("/")
def index():
    return {"ok": True, "service": "HotroSecurityBot"}

def run():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
