"""Run the real HTTP integration suite against isolated local PostgreSQL schemas.

Requires Python dependencies and a managed local Docker daemon. Credentials and
data are generated solely for this test, never printed, and removed afterwards.
"""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import unittest
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import psycopg
import app
from api import index

spec = importlib.util.spec_from_file_location('tracker_suite', ROOT / 'tests' / 'test_app.py')
suite_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite_module)
docker_env = os.environ.copy()
for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
    docker_env.pop(key, None)
docker_env['POSTGRES_PASSWORD'] = secrets.token_hex(24)
container = 'aqua-postgres-test-' + secrets.token_hex(4)
prefix = ['docker', '--host=unix:///var/run/docker.sock']


def docker(*args):
    return subprocess.check_output(prefix + list(args), env=docker_env, text=True, stderr=subprocess.PIPE).strip()


class PostgresTrackerTest(suite_module.TrackerTest):
    def setUp(self):
        self.schema = 'test_' + secrets.token_hex(8)
        with psycopg.connect(base_url, sslmode='disable', autocommit=True) as conn:
            conn.execute('CREATE SCHEMA ' + self.schema)
        app.DATABASE_URL = base_url + '?' + urlencode({'options': '-csearch_path=' + self.schema})
        super().setUp()

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            with psycopg.connect(base_url, sslmode='disable', autocommit=True) as conn:
                conn.execute('DROP SCHEMA ' + self.schema + ' CASCADE')

    def test_cold_start_and_distributed_rate_limit(self):
        self.login()
        self.create_referral()
        self.request('/r/AP-TEST')
        for _ in range(10):
            self.assertEqual(self.request('/api/login', {'username': 'test-admin', 'password': 'invalid'})[0], 401)
        # A new serverless handler shares the same DB and sessions, but no memory.
        os.environ['DATABASE_URL'] = app.DATABASE_URL
        index._ready = False
        replacement = app.ThreadingHTTPServer(('127.0.0.1', 0), index.handler)
        import threading
        worker = threading.Thread(target=replacement.serve_forever, daemon=True)
        worker.start()
        old_server = self.server
        try:
            self.server = replacement
            self.assertEqual(self.request('/api/dashboard')[1]['totals']['visits'], 1)
            self.assertEqual(self.request('/api/login', {'username': 'test-admin', 'password': 'invalid'})[0], 429)
            self.assertEqual(self.request('/api/setup', {'username': 'stranger', 'password': 'a-long-test-password'})[0], 403)
            self.assertEqual(self.request('/r/ap-test')[2]['Location'], '/p/AP-TEST')
            self.assertEqual(self.request('/static/style.css')[0], 200)
            self.assertEqual(self.request('/api/dashboard')[1]['totals']['visits'], 2)
        finally:
            self.server = old_server
            replacement.shutdown()
            replacement.server_close()
            worker.join()


if __name__ == '__main__':
    original_url = app.DATABASE_URL
    original_allow_local = os.environ.get('ALLOW_LOCAL_DATABASE')
    original_env_url = os.environ.get('DATABASE_URL')
    try:
        docker('run', '-d', '--rm', '--name', container, '-e', 'POSTGRES_PASSWORD', '-p', '127.0.0.1::5432', 'postgres:16-alpine')
        port = json.loads(docker('inspect', '--format', '{{json .NetworkSettings.Ports}}', container))['5432/tcp'][0]['HostPort']
        base_url = f'postgresql://postgres:{docker_env["POSTGRES_PASSWORD"]}@127.0.0.1:{port}/postgres'
        for attempt in range(80):
            try:
                with psycopg.connect(base_url, sslmode='disable', connect_timeout=1):
                    break
            except psycopg.OperationalError:
                if attempt == 79:
                    raise RuntimeError('Local PostgreSQL test service did not become ready') from None
                time.sleep(.25)
        os.environ['ALLOW_LOCAL_DATABASE'] = '1'
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(PostgresTrackerTest)
        result = unittest.TextTestRunner(verbosity=2).run(tests)
        if not result.wasSuccessful():
            raise SystemExit(1)
    finally:
        app.DATABASE_URL = original_url
        for key, value in [('ALLOW_LOCAL_DATABASE', original_allow_local), ('DATABASE_URL', original_env_url)]:
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            docker('rm', '-f', container)
        except subprocess.CalledProcessError:
            pass
