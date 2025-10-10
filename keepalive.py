
from flask import Flask
import os

app = Flask(__name__)

@app.get('/')
def index():
    return {'ok': True, 'service': 'HotroSecurityBot_Full_v2'}

def run():
    port = int(os.getenv('PORT', '10000'))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
