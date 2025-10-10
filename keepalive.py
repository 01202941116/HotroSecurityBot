from flask import Flask
app=Flask(__name__)
@app.get('/')
def i(): return {'ok':True}

def run():
 import os; app.run('0.0.0.0', int(os.getenv('PORT','10000')), debug=False, use_reloader=False)
