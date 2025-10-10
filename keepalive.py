import os
from flask import Flask

app = Flask(__name__)

@app.get("/")
def root():
    return "HotroSecurityBot OK"

def run():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
