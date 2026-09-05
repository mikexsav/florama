"""Изолированная проверка зависимостей и SMTP TLS без отправки письма."""
import os
import ssl
import smtplib
import sqlite3
import sys
from pathlib import Path

root=Path('/opt/florama/releases/20260905-v2')
sys.path.insert(0,str(root/'backend'))
for line in Path('/etc/florama.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key,value=line.split('=',1);os.environ[key]=value.strip('"\'')
from app import create_app
app=create_app({'TESTING':True,'DB_PATH':'/opt/florama/data/staging-smoke.sqlite3','COOKIE_SECURE':False})
print('health',app.test_client().get('/api/health').json,flush=True)
try:
    port=int(os.environ.get('SMTP_PORT','2525'))
    host=os.environ.get('SMTP_HOST','smtp.spaceweb.ru')
    context=ssl.create_default_context()
    smtp=smtplib.SMTP_SSL(host,port,timeout=20,context=context) if port==465 else smtplib.SMTP(host,port,timeout=20)
    with smtp:
        smtp.ehlo()
        if port!=465:
            smtp.starttls(context=context);smtp.ehlo()
        smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
    print('SMTP TLS and authentication OK (no email sent)',flush=True)
except Exception as exc:
    print('SMTP_FAILED',type(exc).__name__,flush=True)
    sys.exit(2)
