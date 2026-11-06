"""SQLite for local use; verified-TLS PostgreSQL for serverless deployments."""
import os
import ssl
import sqlite3
from urllib.parse import urlsplit

try:
    import psycopg
except ImportError:
    psycopg = None

INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names = [col.name for col in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


class PostgresCursor:
    def __init__(self, cursor, inserted=False):
        self.cursor = cursor
        self.rowcount = cursor.rowcount
        self.lastrowid = cursor.fetchone()[0] if inserted else None

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class PostgresConnection:
    def __init__(self, url):
        if psycopg is None:
            raise RuntimeError('Install requirements.txt for PostgreSQL support.')
        # Plaintext is permitted only for explicitly enabled, local test databases.
        local_test = os.environ.get('ALLOW_LOCAL_DATABASE') == '1' and urlsplit(url).hostname in ('localhost', '127.0.0.1', '::1')
        options = {'sslmode': 'disable'} if local_test else {'sslmode': 'verify-full', 'sslrootcert': ssl.get_default_verify_paths().cafile}
        self.raw = psycopg.connect(url, row_factory=row_factory, connect_timeout=10, **options)

    def execute(self, sql, parameters=()):
        inserted = sql.lstrip().startswith('INSERT INTO referrals(')
        if inserted:
            sql += ' RETURNING id'
        return PostgresCursor(self.raw.execute(sql.replace('?', '%s'), parameters), inserted)

    def executescript(self, script):
        for statement in script.split(';'):
            if statement.strip():
                self.raw.execute(statement)

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, *args):
        return self.raw.__exit__(*args)

    def close(self):
        self.raw.close()
