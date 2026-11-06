import http.client
import json
import os
import threading
import unittest
from unittest.mock import patch
import app
from api import index


class VercelSafetyTest(unittest.TestCase):
    def test_missing_database_does_not_fall_back_to_temporary_sqlite(self):
        index._ready = False
        with patch.dict(os.environ, {'DATABASE_URL': '', 'POSTGRES_URL': '', 'VERCEL': '1'}):
            server = app.ThreadingHTTPServer(('127.0.0.1', 0), index.handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
                conn.request('GET', '/health')
                response = conn.getresponse()
                self.assertEqual(response.status, 503)
                self.assertIn('error', json.loads(response.read()))
                conn.close()
                with patch.object(app, 'DATABASE_URL', None):
                    with self.assertRaises(RuntimeError):
                        app.initialize()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_serverless_always_disables_public_admin_registration(self):
        handler = object.__new__(index.handler)
        self.assertFalse(handler.local_setup_allowed())
        cookie = handler.set_cookie('aqua_session', 'test-only', 60)[1]
        self.assertIn('; Secure;', cookie)
        self.assertIn('HttpOnly', cookie)


if __name__ == '__main__':
    unittest.main()
