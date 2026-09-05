"""Только UI-тесты на loopback; почтовая заглушка никогда не подключается на VPS."""
import os
import sys
import secrets
from pathlib import Path
from flask import send_from_directory
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
os.environ['DB_PATH']=str(ROOT/'artifacts'/'ui-test.sqlite3')
os.environ['DATA_DIR']=str(ROOT/'artifacts'/'ui-data')
from app import create_app

app=create_app({'SECRET_KEY':secrets.token_hex(32),'COOKIE_SECURE':False,'MAIL_SENDER':lambda email,code:print('LOCAL_TEST_OTP',code,flush=True)})

@app.get('/')
def index():
    return send_from_directory(ROOT/'frontend','index.html')

@app.get('/<path:name>')
def static_asset(name):
    return send_from_directory(ROOT/'frontend',name)

app.run(host='127.0.0.1',port=8009)
