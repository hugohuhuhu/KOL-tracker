import csv
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch
import app


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = app.DB_PATH
        app.DB_PATH = Path(self.temp.name) / 'test.sqlite3'
        app.initialize()
        app.ATTEMPTS.clear()
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookies = {}
        self.csrf = ''

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.DB_PATH = self.old_db
        self.temp.cleanup()

    def request(self, path, body=None, headers=None, authenticated=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        merged = {'User-Agent': 'IntegrationTest'}
        if authenticated:
            merged['Cookie'] = '; '.join(f'{k}={v}' for k,v in self.cookies.items())
            merged['X-CSRF-Token'] = self.csrf
        if headers:
            merged.update(headers)
        if body is not None:
            merged['Content-Type'] = 'application/json'
        conn.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, merged)
        response = conn.getresponse()
        status, response_headers, raw = response.status, dict(response.getheaders()), response.read()
        for key, value in response.getheaders():
            if key.lower() == 'set-cookie' and authenticated:
                cookie = SimpleCookie(value)
                for name, morsel in cookie.items():
                    self.cookies[name] = morsel.value
        conn.close()
        result = json.loads(raw) if raw and 'application/json' in response_headers.get('Content-Type', '') else raw
        return status, result, response_headers

    def login(self):
        credentials = {'username': 'test-admin', 'password': 'test-password-long-enough'}
        self.assertEqual(self.request('/api/setup', credentials)[0], 201)
        status, result, headers = self.request('/api/login', credentials)
        self.assertEqual(status, 200)
        self.csrf = result['csrf']
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        return credentials

    def create_referral(self, **kwargs):
        values = dict(name='旅行創作者', code='AP-TEST', channel='Instagram', note='夏季合作')
        values.update(kwargs)
        status, result, _ = self.request('/api/referrals', values)
        self.assertEqual(status, 201, result)
        return result['id']

    def test_public_and_health(self):
        self.assertEqual(self.request('/health')[1], {'status': 'ok'})
        status, result, _ = self.request('/api/public')
        self.assertEqual(status, 200)
        self.assertEqual(len(result['platforms']), 5)
        self.assertEqual(self.request('/admin')[0], 200)
        self.assertEqual(self.request('/static/../app.py')[0], 404)

    def test_setup_validation_and_single_admin(self):
        self.assertEqual(self.request('/api/setup', dict(username='a', password='short'))[0], 400)
        credentials = self.login()
        self.assertEqual(self.request('/api/setup', credentials)[0], 409)
        with app.db() as c:
            admin = c.execute('SELECT * FROM admin').fetchone()
            self.assertNotEqual(admin['password'], credentials['password'])

    def test_hosting_bootstrap_is_idempotent(self):
        with patch.dict(os.environ, {'ADMIN_USERNAME': 'hosting-admin', 'ADMIN_PASSWORD': 'hosting-test-long-password'}):
            app.bootstrap_admin()
        with patch.dict(os.environ, {'ADMIN_USERNAME': 'changed', 'ADMIN_PASSWORD': 'different-long-password'}):
            app.bootstrap_admin()
        with app.db() as c:
            self.assertEqual(c.execute('SELECT username FROM admin').fetchone()[0], 'hosting-admin')

    def test_admin_authorization_csrf_and_logout(self):
        self.assertEqual(self.request('/api/dashboard')[0], 401)
        self.assertEqual(self.request('/api/referrals', {'name': 'x'})[0], 401)
        self.login()
        self.assertEqual(self.request('/api/referrals', {'name': 'x'}, {'X-CSRF-Token': 'invalid'})[0], 403)
        self.assertEqual(self.request('/api/settings', {}, {'Origin': 'https://evil.test'})[0], 403)
        self.assertEqual(self.request('/api/dashboard')[0], 200)
        self.assertEqual(self.request('/api/logout', {})[0], 200)
        self.assertEqual(self.request('/api/dashboard')[0], 401)

    def test_end_to_end_attribution_and_cookie_dedup(self):
        self.login()
        self.create_referral()
        self.create_referral(code='AP-OTHER', name='第二位 KOL')
        for _ in range(2):
            status, _, headers = self.request('/r/AP-TEST')
            self.assertEqual(status, 302)
            self.assertEqual(headers['Location'], '/p/AP-TEST')
        self.request('/r/AP-OTHER')
        status, _, headers = self.request('/go/AP-TEST/kkday')
        self.assertEqual(status, 302)
        self.assertEqual(headers['Location'], app.DEFAULT_LINKS['kkday'])
        self.request('/go/AP-TEST/klook')
        self.request('/go/_direct/website')
        result = self.request('/api/dashboard?days=30')[1]
        self.assertEqual(result['totals'], dict(visits=3, unique_visitors=1, clicks=2))
        r = result['referrals'][0]
        self.assertEqual((r['visits'], r['unique_visitors'], r['clicks'], r['kkday'], r['klook']), (2, 1, 2, 1, 1))
        self.assertEqual(result['referrals'][1]['visits'], 1)
        self.assertEqual(len(result['daily']), 1)

    def test_disabled_and_unknown_codes(self):
        self.login()
        ref_id = self.create_referral()
        self.request('/r/AP-TEST')
        self.assertEqual(self.request(f'/api/referrals/{ref_id}', dict(name='旅行創作者', active=False))[0], 200)
        for path in ['/r/AP-TEST', '/go/AP-TEST/kkday', '/api/public?code=AP-TEST', '/r/MISSING']:
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request('/api/dashboard')[1]['totals']['visits'], 1)
        self.assertEqual(self.request(f'/api/referrals/{ref_id}', dict(name='旅行創作者', active=True))[0], 200)
        self.assertEqual(self.request('/r/AP-TEST')[0], 302)

    def test_codes_validate_and_duplicates_are_case_insensitive(self):
        self.login()
        self.create_referral()
        self.assertEqual(self.request('/api/referrals', dict(name='重複', code='ap-test'))[0], 409)
        for code in ['a', '../admin', '<script>', 'bad code']:
            self.assertEqual(self.request('/api/referrals', dict(name='a', code=code))[0], 400)
        self.create_referral(code='')
        self.assertEqual(len(self.request('/api/dashboard')[1]['referrals']), 2)

    def test_settings_redirect_and_hide_empty_platform(self):
        self.login()
        for value in ['javascript:alert(1)', 'http://example.com', 'https://user:password@example.com', 'https://example.com/\r\nX:1']:
            self.assertEqual(self.request('/api/settings', {'website': value})[0], 400)
        self.assertEqual(self.request('/api/settings', dict(website='https://example.com/new', klook=''))[0], 200)
        self.assertEqual(self.request('/go/_direct/website')[2]['Location'], 'https://example.com/new')
        self.assertEqual(self.request('/go/_direct/klook')[0], 404)
        self.assertNotIn('klook', self.request('/api/public')[1]['platforms'])
        app.initialize()  # Re-running setup must preserve configured data.
        self.assertEqual(self.request('/api/settings')[1]['website'], 'https://example.com/new')

    def test_bot_filter_and_preview_do_not_count(self):
        self.login()
        self.create_referral()
        self.request('/r/AP-TEST', headers={'User-Agent': 'facebookexternalhit/1.1'})
        self.request('/go/AP-TEST/kkday', headers={'User-Agent': 'Googlebot'})
        self.request('/p/AP-TEST')
        self.request('/api/public?code=AP-TEST')
        self.assertEqual(self.request('/api/dashboard')[1]['totals']['visits'], 0)
        self.assertEqual(self.request('/api/dashboard')[1]['totals']['clicks'], 0)

    def test_csv_export_and_formula_safety(self):
        self.login()
        self.create_referral(name='=FORMULA', channel='+unsafe')
        self.request('/r/AP-TEST')
        status, body, headers = self.request('/api/export?days=all')
        self.assertEqual(status, 200)
        rows = list(csv.reader(io.StringIO(body.decode('utf-8-sig'))))
        self.assertEqual(rows[1][0], "'=FORMULA")
        self.assertEqual(rows[1][2], "'+unsafe")
        self.assertEqual(rows[1][4], '1')
        self.assertIn('attachment', headers['Content-Disposition'])

    def test_date_filter_and_taipei_midnight(self):
        self.login()
        ref_id = self.create_referral()
        with app.db() as c:
            for date in ('2026-10-30T15:59:59+00:00', '2026-10-30T16:00:00+00:00', '2026-11-06T01:00:00+00:00'):
                c.execute('INSERT INTO events(referral_id,kind,visitor,created_at) VALUES(?,?,?,?)', (ref_id, 'visit', 'visitor', date))
        class FixedDatetime(app.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 6, 12, tzinfo=app.timezone.utc).astimezone(tz)
        with patch.object(app, 'datetime', FixedDatetime):
            result = self.request('/api/dashboard?days=7')[1]
        self.assertEqual(result['totals']['visits'], 2)
        self.assertEqual(result['daily'][0]['day'], '2026-10-31')
        self.assertEqual(self.request('/api/dashboard?days=oops')[0], 400)

    def test_login_throttle_and_expired_session(self):
        credentials = self.login()
        with app.db() as c:
            c.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.request('/api/dashboard')[0], 401)
        for _ in range(10):
            self.assertEqual(self.request('/api/login', dict(username='wrong', password='invalid'))[0], 401)
        self.assertEqual(self.request('/api/login', credentials)[0], 429)


if __name__ == '__main__':
    unittest.main()
