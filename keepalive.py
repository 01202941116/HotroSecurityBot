
from flask import Flask
import os
app = Flask(__name__)

@app.get("/")
def index():
    return {"ok": True, "app": "HotroSecurityBot_PRO_v207", "status": "running"}

def run():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
