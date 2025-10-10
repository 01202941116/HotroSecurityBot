
from flask import Flask
import os
app = Flask(__name__)

@app.get('/')
def index():
    return {'ok': True, 'service': 'HotroSecBot_New_v1'}

def run():
    port = int(os.getenv('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
