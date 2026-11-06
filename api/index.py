"""Vercel Python Function entrypoint. All routes retain their original paths."""
import os
import threading
from app import Handler, bootstrap_admin, initialize

_lock = threading.Lock()
_ready = False


class handler(Handler):
    def prepare(self):
        global _ready
        if _ready:
            return True
        with _lock:
            if _ready:
                return True
            try:
                # Never use a temporary SQLite database or permit local setup on Vercel.
                if not (os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL')):
                    raise RuntimeError('Persistent database is missing')
                initialize()
                bootstrap_admin()
                _ready = True
            except Exception:
                # Connection errors may contain credentials; do not log exception text.
                self.error(503, '服務設定尚未完成，請管理員確認雲端資料庫與管理員環境變數。')
                return False
        return True

    def local_setup_allowed(self):
        return False

    def set_cookie(self, name, value, age):
        return ('Set-Cookie', f'{name}={value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={age}')

    def do_GET(self):
        if self.prepare():
            super().do_GET()

    def do_POST(self):
        if self.prepare():
            super().do_POST()
