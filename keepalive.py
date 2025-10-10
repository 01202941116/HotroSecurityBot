from flask import Flask
from threading import Thread
import requests, time

app = Flask(__name__)

@app.route('/')
def home():
    return "OK", 200

def run():
    app.run(host='0.0.0.0', port=10000)

def ping():
    while True:
        try:
            requests.get("https://hotrosecuritybot.onrender.com")
        except:
            pass
        time.sleep(300)  # 5 phút ping 1 lần

def start_keepalive():
    Thread(target=run).start()
    Thread(target=ping).start()
