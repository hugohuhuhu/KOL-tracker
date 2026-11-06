"""Aqua Planet referral tracker. Python 3.12+, no third-party dependencies."""
import argparse
import csv
import getpass
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('DATABASE_PATH', ROOT / 'data' / 'aqua.sqlite3'))
PLATFORMS = ('facebook', 'instagram', 'website', 'kkday', 'klook')
DEFAULT_LINKS = {
    'facebook': 'https://www.facebook.com/search/top/?q=aqua%20planet',
    'instagram': 'https://www.instagram.com/aquaplanetph/',
    'website': 'https://www.aquaplanet.ph/',
    'kkday': 'https://www.kkday.com/zh-tw/product/132050-aqua-planet-waterpark-ticket-clark-philippines',
    'klook': 'https://www.klook.com/zh-TW/activity/18285-aqua-planet-pass-subic-clark/?spm=SearchResult.SearchResult_LIST&clickId=d74da8f078',
}
LOCK = threading.Lock()
ATTEMPTS = {}


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS referrals(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL COLLATE NOCASE, name TEXT NOT NULL, channel TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, referral_id INTEGER NOT NULL REFERENCES referrals(id), kind TEXT NOT NULL, destination TEXT, visitor TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_date ON events(created_at, referral_id);
        CREATE INDEX IF NOT EXISTS events_referral ON events(referral_id, kind, visitor);
        ''')
        c.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (json.dumps(dict(title='Aqua Planet', subtitle='把日常留在岸上。一起跳進菲律賓克拉克的陽光與浪花。', public_url='', **DEFAULT_LINKS)),))
    os.chmod(DB_PATH, 0o600)


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()


def create_admin(username, password):
    if not isinstance(username, str) or not 1 <= len(username.strip()) <= 60:
        raise ValueError('請輸入管理員帳號（最多 60 字）。')
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('密碼需為 12–256 個字元。')
    salt = secrets.token_hex(16)
    hashed = password_hash(password, salt)
    with db() as c:
        c.execute('INSERT INTO admin VALUES(1,?,?,?)', (username.strip(), salt, hashed))


def bootstrap_admin():
    """Optional first-deploy credentials from hosting variables, never logged."""
    with db() as c:
        if c.execute('SELECT 1 FROM admin').fetchone():
            return
    username, password = os.environ.get('ADMIN_USERNAME'), os.environ.get('ADMIN_PASSWORD')
    if username is not None or password is not None:
        create_admin(username, password)


def settings(c):
    return json.loads(c.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])


def valid_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(x) < 32 for x in value):
        return False
    u = urlsplit(value)
    return bool(u.scheme == 'https' and u.hostname and not u.username and not u.password)


class Handler(BaseHTTPRequestHandler):
    server_version = 'AquaPlanet'

    def log_message(self, fmt, *args):
        # Do not log URL parameters, bodies, cookies, or credentials.
        pass

    def respond(self, status, body=b'', content_type='application/json; charset=utf-8', headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for k, v in (headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def error(self, status, message):
        self.respond(status, {'error': message})

    def cookie(self, name):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            return cookies[name].value if name in cookies else ''
        except Exception:
            return ''

    def set_cookie(self, name, value, age):
        secure = '; Secure' if os.environ.get('COOKIE_SECURE') == '1' else ''
        return ('Set-Cookie', f'{name}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={age}{secure}')

    def session(self):
        token = hashlib.sha256(self.cookie('aqua_session').encode()).hexdigest()
        with db() as c:
            return c.execute('SELECT * FROM sessions WHERE token=? AND expires>?', (token, time.time())).fetchone()

    def read_body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length < 0 or length > 16384:
            raise ValueError('請求內容過大。')
        data = json.loads(self.rfile.read(length) or b'{}')
        if not isinstance(data, dict):
            raise ValueError('無效的請求格式。')
        return data

    def do_GET(self):
        try:
            self.get_route()
        except (ValueError, TypeError):
            self.error(400, '無效的參數。')
        except Exception:
            self.error(500, '服務暫時無法使用，請稍後重試。')

    def get_route(self):
        url = urlsplit(self.path)
        path = url.path
        if path == '/favicon.ico':
            return self.respond(204, content_type='image/x-icon')
        if path == '/health':
            with db() as c:
                c.execute('SELECT 1 FROM settings').fetchone()
            return self.respond(200, {'status': 'ok'})
        if path in ('/', '/admin', '/admin/') or re.fullmatch(r'/p/[A-Za-z0-9_-]{3,40}', path):
            filename = 'admin.html' if path.startswith('/admin') else 'landing.html'
            return self.respond(200, (ROOT / 'static' / filename).read_bytes(), 'text/html; charset=utf-8')
        if path.startswith('/static/'):
            filename = path.removeprefix('/static/')
            allowed = {'style.css': 'text/css', 'admin.js': 'text/javascript', 'landing.js': 'text/javascript'}
            if filename in allowed:
                return self.respond(200, (ROOT / 'static' / filename).read_bytes(), allowed[filename] + '; charset=utf-8')
        if path == '/api/session':
            session = self.session()
            with db() as c:
                initialized = bool(c.execute('SELECT 1 FROM admin').fetchone())
            return self.respond(200, {'authenticated': bool(session), 'csrf': session['csrf'] if session else '', 'initialized': initialized, 'local_setup': self.client_address[0] in ('127.0.0.1', '::1')})
        if path == '/api/public':
            code = parse_qs(url.query).get('code', [''])[0]
            with db() as c:
                ref = c.execute('SELECT code FROM referrals WHERE code=? AND active=1', (code,)).fetchone() if code else None
                if code and not ref:
                    return self.error(404, '這個推薦連結不存在或已停用。')
                config = settings(c)
            return self.respond(200, {'title': config['title'], 'subtitle': config['subtitle'], 'code': ref['code'] if ref else '', 'platforms': [p for p in PLATFORMS if config[p]]})
        match = re.fullmatch(r'/r/([A-Za-z0-9_-]{3,40})', path)
        if match:
            with db() as c:
                ref = c.execute('SELECT * FROM referrals WHERE code=? AND active=1', (match[1],)).fetchone()
                if not ref:
                    return self.respond(404, '推薦連結不存在或已停用。', 'text/plain; charset=utf-8')
                visitor, headers = self.record(c, ref['id'], 'visit', None)
            return self.respond(302, headers=headers + [('Location', '/p/' + ref['code'])])
        match = re.fullmatch(r'/go/([A-Za-z0-9_-]{3,40}|_direct)/(facebook|instagram|website|kkday|klook)', path)
        if match:
            code, destination = match.groups()
            with db() as c:
                config = settings(c)
                target = config[destination]
                if not target or not valid_url(target):
                    return self.error(404, '這個平台的連結尚未開放。')
                headers = []
                if code != '_direct':
                    ref = c.execute('SELECT * FROM referrals WHERE code=? AND active=1', (code,)).fetchone()
                    if not ref:
                        return self.error(404, '推薦連結不存在或已停用。')
                    _, headers = self.record(c, ref['id'], 'click', destination)
            return self.respond(302, headers=headers + [('Location', target)])
        if path in ('/api/dashboard', '/api/settings', '/api/export'):
            if not self.session():
                return self.error(401, '請先登入後台。')
            with db() as c:
                if path == '/api/settings':
                    return self.respond(200, settings(c))
                data = self.dashboard(c, parse_qs(url.query))
            if path == '/api/export':
                stream = io.StringIO()
                writer = csv.writer(stream)
                writer.writerow(['KOL', '推薦碼', '渠道', '狀態', '造訪次數', '不重複訪客', '平台點擊', *PLATFORMS])
                def safe(v):
                    return "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v
                for r in data['referrals']:
                    writer.writerow([safe(r['name']), r['code'], safe(r['channel']), '啟用' if r['active'] else '停用', r['visits'], r['unique_visitors'], r['clicks'], *[r[p] for p in PLATFORMS]])
                return self.respond(200, '\ufeff' + stream.getvalue(), 'text/csv; charset=utf-8', [('Content-Disposition', 'attachment; filename="aqua-kol-report.csv"')])
            return self.respond(200, data)
        self.error(404, '找不到這個頁面。')

    def record(self, c, referral_id, kind, destination):
        visitor = self.cookie('aqua_visitor')
        headers = []
        if not re.fullmatch(r'[a-f0-9]{32}', visitor):
            visitor = secrets.token_hex(16)
            headers.append(self.set_cookie('aqua_visitor', visitor, 365 * 86400))
        # Basic crawler filtering; counts remain request-based, not fraud-proof analytics.
        if self.command == 'GET' and not re.search(r'bot|crawler|spider|preview|facebookexternalhit|headless', self.headers.get('User-Agent', ''), re.I):
            c.execute('INSERT INTO events(referral_id,kind,destination,visitor,created_at) VALUES(?,?,?,?,?)', (referral_id, kind, destination, hashlib.sha256(visitor.encode()).hexdigest(), now()))
        return visitor, headers

    def dashboard(self, c, query):
        days = query.get('days', ['30'])[0]
        if days not in ('7', '30', '90', 'all'):
            raise ValueError('Invalid period')
        # Display and date boundaries use Asia/Taipei (UTC+8, no DST).
        today = datetime.now(timezone(timedelta(hours=8))).date()
        start_day = today - timedelta(days=int(days) - 1) if days != 'all' else None
        since = datetime.combine(start_day, datetime.min.time(), timezone(timedelta(hours=8))).astimezone(timezone.utc).isoformat(timespec='seconds') if start_day else ''
        rows = c.execute('''SELECT r.*, COUNT(CASE WHEN e.kind='visit' THEN 1 END) visits,
            COUNT(DISTINCT CASE WHEN e.kind='visit' THEN e.visitor END) unique_visitors,
            COUNT(CASE WHEN e.kind='click' THEN 1 END) clicks,
            COUNT(CASE WHEN e.destination='facebook' THEN 1 END) facebook,
            COUNT(CASE WHEN e.destination='instagram' THEN 1 END) instagram,
            COUNT(CASE WHEN e.destination='website' THEN 1 END) website,
            COUNT(CASE WHEN e.destination='kkday' THEN 1 END) kkday,
            COUNT(CASE WHEN e.destination='klook' THEN 1 END) klook
            FROM referrals r LEFT JOIN events e ON e.referral_id=r.id AND e.created_at>=?
            GROUP BY r.id ORDER BY visits DESC, r.id DESC''', (since,)).fetchall()
        totals = c.execute('''SELECT COUNT(CASE WHEN kind='visit' THEN 1 END) visits,
            COUNT(DISTINCT CASE WHEN kind='visit' THEN visitor END) unique_visitors,
            COUNT(CASE WHEN kind='click' THEN 1 END) clicks FROM events WHERE created_at>=?''', (since,)).fetchone()
        daily = c.execute("SELECT date(created_at,'+8 hours') day, COUNT(CASE WHEN kind='visit' THEN 1 END) visits, COUNT(CASE WHEN kind='click' THEN 1 END) clicks FROM events WHERE created_at>=? GROUP BY day ORDER BY day", (since,)).fetchall()
        config = settings(c)
        return {'referrals': [dict(r) for r in rows], 'totals': dict(totals), 'daily': [dict(r) for r in daily], 'days': days, 'public_url': config['public_url'], 'configured_platforms': len([p for p in PLATFORMS if config[p]]), 'today': str(today)}

    def do_POST(self):
        try:
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                return self.error(403, '不允許跨網站請求。')
            data = self.read_body()
            path = urlsplit(self.path).path
            if path == '/api/setup':
                if self.client_address[0] not in ('127.0.0.1', '::1'):
                    return self.error(403, '請先在伺服器執行 python3 app.py --create-admin 建立管理員。')
                with LOCK:
                    with db() as c:
                        if c.execute('SELECT 1 FROM admin').fetchone():
                            return self.error(409, '管理員已建立，請登入。')
                    create_admin(data.get('username'), data.get('password'))
                return self.respond(201, {'ok': True})
            if path == '/api/login':
                ip = self.client_address[0]
                with LOCK:
                    attempts = [t for t in ATTEMPTS.get(ip, []) if t > time.time() - 900]
                    if len(attempts) >= 10:
                        return self.error(429, '登入嘗試過多，請 15 分鐘後再試。')
                    attempts.append(time.time())
                    ATTEMPTS[ip] = attempts
                with db() as c:
                    admin = c.execute('SELECT * FROM admin').fetchone()
                    password = data.get('password', '')
                    if not isinstance(password, str) or len(password) > 256:
                        return self.error(401, '帳號或密碼不正確。')
                    calculated = password_hash(password, admin['salt'] if admin else '00' * 16)
                    if not admin or not hmac.compare_digest(calculated, admin['password']) or data.get('username') != admin['username']:
                        return self.error(401, '帳號或密碼不正確。')
                    token, csrf = secrets.token_hex(32), secrets.token_hex(32)
                    c.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
                    c.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + 12 * 3600))
                with LOCK:
                    ATTEMPTS.pop(ip, None)
                return self.respond(200, {'csrf': csrf}, headers=[self.set_cookie('aqua_session', token, 12 * 3600)])
            session = self.session()
            if not session:
                return self.error(401, '請先登入後台。')
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
                return self.error(403, '安全驗證失效，請重新整理頁面。')
            if path == '/api/logout':
                with db() as c:
                    c.execute('DELETE FROM sessions WHERE token=?', (session['token'],))
                return self.respond(200, {'ok': True}, headers=[self.set_cookie('aqua_session', '', 0)])
            if path == '/api/settings':
                with db() as c:
                    config = settings(c)
                    for key in ('title', 'subtitle', 'public_url', *PLATFORMS):
                        value = data.get(key, config[key])
                        if not isinstance(value, str):
                            raise ValueError('設定格式錯誤。')
                        value = value.strip()
                        if key in (*PLATFORMS, 'public_url') and value and not valid_url(value):
                            raise ValueError('網址必須為有效的 HTTPS 網址，且不可包含帳號或密碼。')
                        if key in ('title', 'subtitle') and (not value or len(value) > 160):
                            raise ValueError('標題與簡介必填，且最多 160 字。')
                        config[key] = value.rstrip('/') if key == 'public_url' else value
                    c.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(config),))
                return self.respond(200, {'ok': True})
            if path == '/api/referrals' or re.fullmatch(r'/api/referrals/\d+', path):
                name, channel, note = (data.get(k, '').strip() for k in ('name', 'channel', 'note'))
                if not name or len(name) > 80 or len(channel) > 80 or len(note) > 500:
                    raise ValueError('KOL 名稱必填（最多 80 字）；渠道最多 80 字，備註最多 500 字。')
                with db() as c:
                    if path == '/api/referrals':
                        code = data.get('code', '').strip() or 'AP-' + secrets.token_hex(4).upper()
                        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{2,39}', code) or code.lower() == '_direct':
                            raise ValueError('推薦碼需為 3–40 個英文字母、數字、底線或連字號，且以英數字開頭。')
                        cur = c.execute('INSERT INTO referrals(code,name,channel,note,created_at) VALUES(?,?,?,?,?)', (code, name, channel, note, now()))
                        ref_id = cur.lastrowid
                    else:
                        ref_id = int(path.rsplit('/', 1)[1])
                        active = data.get('active', True)
                        if not isinstance(active, bool):
                            raise ValueError('無效的啟用狀態。')
                        cur = c.execute('UPDATE referrals SET name=?,channel=?,note=?,active=? WHERE id=?', (name, channel, note, int(active), ref_id))
                        if not cur.rowcount:
                            return self.error(404, '找不到這個推薦碼。')
                return self.respond(201 if path == '/api/referrals' else 200, {'id': ref_id})
            self.error(404, '找不到這個功能。')
        except sqlite3.IntegrityError:
            self.error(409, '這個推薦碼已經存在，請換一個。')
        except (ValueError, TypeError, AttributeError) as exc:
            self.error(400, str(exc) if isinstance(exc, ValueError) else '請檢查輸入格式。')
        except Exception:
            self.error(500, '服務暫時無法使用，請稍後重試。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default=os.environ.get('HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8000')))
    parser.add_argument('--create-admin', action='store_true')
    args = parser.parse_args()
    initialize()
    if args.create_admin:
        username = input('管理員帳號：')
        password = getpass.getpass('密碼（至少 12 個字元）：')
        if password != getpass.getpass('再次輸入密碼：'):
            raise SystemExit('密碼不一致。')
        try:
            create_admin(username, password)
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise SystemExit('無法建立管理員：' + str(exc))
        print('管理員已建立。')
        return
    try:
        bootstrap_admin()
    except ValueError as exc:
        raise SystemExit('管理員環境變數設定錯誤：' + str(exc))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'Aqua Planet running on port {args.port}; admin path: /admin', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
