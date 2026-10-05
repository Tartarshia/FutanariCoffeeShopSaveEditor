import http.client
import json
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import web_server

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), web_server.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        c.request('GET', path, headers=headers or {})
        r = c.getresponse()
        result = r.status, r.read(), r.getheaders()
        c.close()
        return result

    def test_host_origin_and_token_checks(self):
        self.assertEqual(self.request('/', {'Host':'attacker.example'})[0], 400)
        self.assertEqual(self.request('/', {'Origin':'http://attacker.example'})[0], 400)
        self.assertEqual(self.request('/api/saves')[0], 400)
        headers = {'X-Editor-Token':web_server.TOKEN}
        self.assertEqual(self.request('/api/saves', headers)[0], 200)
        headers['Sec-Fetch-Site'] = 'cross-site'
        self.assertEqual(self.request('/api/saves', headers)[0], 400)

    def test_static_and_cookie(self):
        status, body, headers = self.request('/')
        self.assertEqual(status, 200)
        self.assertNotIn(b'__TOKEN__', body)
        self.assertIn('HttpOnly', dict(headers)['Set-Cookie'])
        self.assertEqual(self.request('/../codec.py')[0], 404)
        self.assertEqual(self.request('/app.js')[0], 200)

    def test_job_traversal_refused(self):
        self.assertEqual(self.request('/api/fields?job=../', {'X-Editor-Token':web_server.TOKEN})[0], 400)
        self.assertEqual(self.request('/api/preview-file?job=../&name=../codec.py',
                                      {'X-Editor-Token':web_server.TOKEN})[0],400)
        self.assertEqual(self.request('/api/portrait?job=../&id=0')[0],400)

    def test_steam_mutation_requires_token_confirmation_and_one_id(self):
        def post(data, token=True):
            c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
            headers={'Content-Type':'application/json'}
            if token:headers['X-Editor-Token']=web_server.TOKEN
            c.request('POST','/api/steam',json.dumps(data),headers)
            response=c.getresponse();result=response.status;response.read();c.close()
            return result
        with patch('web_server.launch',return_value='test') as launch:
            self.assertEqual(post({'operation':'unlock','achievement':'ACH_TEST','confirmed':True},False),400)
            self.assertEqual(post({'operation':'unlock','achievement':'ACH_TEST'}),400)
            self.assertEqual(post({'operation':'unlock','achievement':['ONE','TWO'],'confirmed':True}),400)
            launch.assert_not_called()
            self.assertEqual(post({'operation':'list'}),200)
            self.assertEqual(launch.call_args.args[0]['operation'],'list')
            self.assertEqual(post({'operation':'unlock','achievement':'ACH_TEST','confirmed':True}),200)
            self.assertEqual(launch.call_args.args[0]['achievement'],'ACH_TEST')
