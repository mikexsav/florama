"""OTP привязан к сценарию; код одноразовый даже при параллельных запросах."""
import hashlib
import hmac
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from functools import wraps
from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import BadRequest, Forbidden, Unauthorized, TooManyRequests
from store import transaction

auth = Blueprint('auth', __name__, url_prefix='/api/auth')
COOKIE = 'crewloom_session'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def keyed(value):
    return hmac.new(current_app.config['SECRET_KEY'].encode(), value.encode(), hashlib.sha256).hexdigest()


def public_user(row):
    return {'id': row['id'], 'email': row['email'], 'firstName': row['first_name'], 'lastName': row['last_name']}


def payload():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise BadRequest('Ожидается JSON-объект.')
    return value


def text_field(value, name, limit=100, required=False):
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise BadRequest(f'Некорректное поле: {name}.')
    value = value.strip()
    if required and not value:
        raise BadRequest(f'Заполните поле: {name}.')
    return value


def limit(key, count, seconds):
    now = int(time.time())
    with transaction(current_app.config['DB_PATH'], immediate=True) as c:
        c.execute('DELETE FROM rate_limits WHERE expires_at <= ?', (now,))
        row = c.execute('SELECT count FROM rate_limits WHERE key=?', (key,)).fetchone()
        if row and row['count'] >= count:
            raise TooManyRequests('Слишком много запросов. Повторите позже.')
        c.execute('INSERT INTO rate_limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, now+seconds))


def require_user(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        bearer = request.headers.get('Authorization', '')
        token = bearer[7:] if bearer.startswith('Bearer ') else request.cookies.get(COOKIE, '')
        if not token or len(token) > 200:
            raise Unauthorized('Войдите в аккаунт.')
        with transaction(current_app.config['DB_PATH']) as c:
            row = c.execute('''SELECT u.*, s.csrf, s.token_hash FROM sessions s
                JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?''',
                (digest(token), int(time.time()))).fetchone()
        if not row:
            raise Unauthorized('Сессия истекла. Войдите снова.')
        if not bearer and request.method not in ('GET','HEAD','OPTIONS'):
            if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''), row['csrf']):
                raise Forbidden('Не удалось проверить запрос. Обновите страницу.')
        g.user = row
        return fn(*args, **kwargs)
    return wrapped


def send_email(email, code):
    override = current_app.config.get('MAIL_SENDER')
    if override:
        return override(email, code)
    sender = os.environ['SMTP_USER']
    message = EmailMessage()
    message['From'] = os.getenv('SMTP_FROM', sender)
    message['To'] = email
    message['Subject'] = 'Код входа — FLORAMA'
    message.set_content(f'Ваш код FLORAMA: {code}\nДействует 5 минут. Не сообщайте его другим людям.\nЕсли вы не запрашивали код, проигнорируйте письмо.')
    port = int(os.getenv('SMTP_PORT', '2525'))
    context = ssl.create_default_context()
    host = os.getenv('SMTP_HOST', 'smtp.spaceweb.ru')
    smtp = smtplib.SMTP_SSL(host, port, timeout=20, context=context) if port == 465 else smtplib.SMTP(host, port, timeout=20)
    with smtp:
        smtp.ehlo()
        if port != 465:
            smtp.starttls(context=context)
            smtp.ehlo()
        smtp.login(sender, os.environ['SMTP_PASSWORD'])
        smtp.send_message(message)


def credentials(data):
    email = text_field(data.get('email', ''), 'Почта', 254, True).lower()
    mode = data.get('mode', 'login')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or mode not in ('login', 'register'):
        raise BadRequest('Введите корректную почту и способ входа.')
    return email, mode


@auth.post('/send-code')
def send_code():
    email, mode = credentials(payload())
    limit('mail-ip:'+keyed(request.remote_addr or ''), 20, 3600)
    limit('mail:'+keyed(email), 1, 60)
    code = f'{secrets.randbelow(1000000):06d}'
    hashed = keyed(email+'|'+mode+'|'+code)
    now = int(time.time())
    with transaction(current_app.config['DB_PATH'], immediate=True) as c:
        user = c.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        # Одинаковый ответ не раскрывает наличие чужой почты в базе.
        eligible = bool(user) if mode == 'login' else not user
        if eligible:
            c.execute('''INSERT INTO codes(email,code_hash,expires_at,attempts,last_sent_at,mode)
                VALUES (?,?,?,0,?,?) ON CONFLICT(email) DO UPDATE SET code_hash=excluded.code_hash,
                expires_at=excluded.expires_at,attempts=0,last_sent_at=excluded.last_sent_at,mode=excluded.mode''',
                (email, hashed, now+300, now, mode))
    if eligible:
        try:
            send_email(email, code)
        except Exception as exc:
            with transaction(current_app.config['DB_PATH']) as c:
                c.execute('DELETE FROM codes WHERE email=? AND code_hash=?', (email, hashed))
            current_app.logger.error('smtp_failure type=%s request_id=%s', type(exc).__name__, g.request_id)
            return jsonify(error='Почтовый сервис недоступен. Повторите позже.', requestId=g.request_id), 502
    return jsonify(message='Если почта подходит для выбранного действия, код отправлен. Для существующего аккаунта выберите «Войти».', retryAfter=60)


@auth.post('/verify-code')
def verify_code():
    data = payload()
    email, mode = credentials(data)
    code = str(data.get('code', '')).strip()
    if not re.fullmatch('[0-9]{6}', code):
        raise BadRequest('Введите шестизначный код.')
    first = text_field(data.get('firstName', ''), 'Имя', 80, mode == 'register')
    last = text_field(data.get('lastName', ''), 'Фамилия', 80, mode == 'register')
    limit('verify:'+keyed(request.remote_addr or ''), 60, 600)
    now = int(time.time())
    error = False
    with transaction(current_app.config['DB_PATH'], immediate=True) as c:
        row = c.execute('SELECT * FROM codes WHERE email=?', (email,)).fetchone()
        if not row or row['expires_at'] <= now or row['attempts'] >= 5 or row['mode'] != mode:
            error = True
        elif not hmac.compare_digest(row['code_hash'], keyed(email+'|'+mode+'|'+code)):
            c.execute('UPDATE codes SET attempts=attempts+1 WHERE email=?', (email,))
            error = True
        else:
            user = c.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            if mode == 'register' and not user:
                c.execute('INSERT INTO users(email,first_name,last_name,created_at) VALUES (?,?,?,?)', (email,first,last,now))
                user = c.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            if not user:
                error = True
            else:
                c.execute('DELETE FROM codes WHERE email=?', (email,))
                c.execute('DELETE FROM sessions WHERE expires_at<=?', (now,))
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
                c.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (digest(token),user['id'],csrf,now+604800,now))
    if error:
        raise BadRequest('Неверный или просроченный код. Запросите новый код для выбранного действия.')
    response = jsonify(user=public_user(user), csrfToken=csrf)
    response.set_cookie(COOKIE, token, max_age=604800, httponly=True, secure=current_app.config['COOKIE_SECURE'], samesite='Lax', path='/')
    return response


@auth.get('/me')
@require_user
def me():
    return jsonify(user=public_user(g.user), csrfToken=g.user['csrf'])


@auth.post('/logout')
@require_user
def logout():
    with transaction(current_app.config['DB_PATH']) as c:
        c.execute('DELETE FROM sessions WHERE token_hash=?', (g.user['token_hash'],))
    response = jsonify(message='Вы вышли из аккаунта.')
    response.delete_cookie(COOKIE, path='/')
    return response
