"""Запускается root на VPS: сохраняет SMTP-настройки, добавляет секрет без вывода."""
import os
import secrets
from pathlib import Path

path=Path('/etc/florama.env')
text=path.read_text() if path.exists() else ''
values={}
for line in text.splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key,value=line.split('=',1); values[key]=value
values.setdefault('APP_SECRET',secrets.token_hex(48))
values['APP_ORIGINS']='https://crewloom.ru,https://www.crewloom.ru'
values['DB_PATH']='/opt/florama/data/florama.sqlite3'
values['DATA_DIR']='/opt/florama/data'
values['COOKIE_SECURE']='true'
path.write_text('\n'.join(k+'='+v for k,v in values.items())+'\n')
path.chmod(0o600)
print('Environment updated; secrets not displayed.')
