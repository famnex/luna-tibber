import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, Mock
import luna
import web

class ScheduleTests(unittest.TestCase):
    def test_overnight_belongs_to_start_day(self):
        rows=[{'days':[4],'start':'23:00','end':'02:00','mode':'on'}]
        web.validate_schedules(rows)
        self.assertEqual(web.schedule_at(rows,datetime(2026,10,24,1,0))[0],'on')
        self.assertEqual(web.schedule_at(rows,datetime(2026,10,24,2,0))[0],'off')
    def test_first_row_wins(self):
        rows=[{'days':[4],'start':'01:00','end':'03:00','mode':'off'},
              {'days':[4],'start':'00:00','end':'06:00','mode':'on'}]
        self.assertEqual(web.schedule_at(rows,datetime(2026,10,23,2))[0],'off')
    def test_bad_time_and_mode_rejected(self):
        for row in [{'days':[0],'start':'24:00','end':'06:00','mode':'on'},
                    {'days':[0],'start':'00:00','end':'00:00','mode':'on'},
                    {'days':[7],'start':'00:00','end':'06:00','mode':'on'}]:
            with self.assertRaises(ValueError):web.validate_schedules([row])

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.folder=Path(self.tmp.name)
        self.app=web.Dashboard(self.folder,start_worker=False)
    def tearDown(self):self.tmp.cleanup()
    def test_missing_credentials_are_specific(self):
        with self.assertRaisesRegex(ValueError,'Seriennummer.*Installateurpasswort'):
            self.app.action('mode',{'mode':'on'})
        self.assertEqual(self.app.mode,'off')
    def test_no_secret_returned_and_blank_retains(self):
        self.app.save_settings({'password':'secret-password','tibber_token':'secret-token'})
        self.app.save_settings({'password':'','tibber_token':''})
        self.assertEqual(self.app.config()['password'],'secret-password')
        status=json.dumps(self.app.snapshot())
        self.assertNotIn('secret-password',status)
        self.assertNotIn('secret-token',status)
    def test_serial_change_revokes_commission(self):
        luna.write_json(self.folder/'commissioned.json',{'serial':'old'})
        self.app.save_settings({'expected_serial':'new'})
        self.assertFalse((self.folder/'commissioned.json').exists())
    def test_writes_require_idle(self):
        self.app.mode='smart'
        with self.assertRaises(ValueError):self.app.save_settings({'target_soc':75})
    def test_on_requires_test(self):
        self.app.save_settings({'expected_serial':'serial','password':'secret'})
        with self.assertRaisesRegex(ValueError,'Ladetest'):
            self.app.action('mode',{'mode':'on'})
    def test_manual_mode_is_bounded_and_resets_after_restart(self):
        self.app.save_settings({'expected_serial':'serial','password':'secret'})
        luna.write_json(self.folder/'commissioned.json',{'serial':'serial'})
        self.app.action('mode',{'mode':'on','minutes':10})
        self.assertEqual(self.app.mode,'on')
        self.assertIsNotNone(self.app.until)
        self.assertEqual(web.Dashboard(self.folder,start_worker=False).mode,'off')
    def test_manual_still_obeys_soc_and_ac(self):
        c={**luna.DEFAULT,'_manual':True}
        s={'soc':61,'battery_status':2,'ac_charge_enabled':True}
        self.assertTrue(luna.decide(c,s,[],datetime.now(timezone.utc))[0])
        self.assertFalse(luna.decide(c,{**s,'soc':90},[],datetime.now(timezone.utc))[0])
        self.assertFalse(luna.decide(c,{**s,'ac_charge_enabled':False},[],datetime.now(timezone.utc))[0])
    def test_adopt_requires_successful_probe(self):
        self.app.device={'serial':'unconfirmed'}
        with self.assertRaises(ValueError):self.app.action('adopt-serial',{})

class HTTPTests(unittest.TestCase):
    def setUp(self):
        import threading, hashlib
        from collections import deque
        from http.server import ThreadingHTTPServer
        self.server=ThreadingHTTPServer(('127.0.0.1',0),web.Handler)
        self.server.allowed_hosts={'127.0.0.1'}
        self.server.auth={'salt':'00'*16,'hash':hashlib.pbkdf2_hmac('sha256',b'test-password',bytes(16),300000).hex()}
        self.server.auth_lock=threading.Lock()
        self.server.sessions={}
        self.server.attempts=deque()
        self.server.app=Mock()
        self.server.app.snapshot.return_value={'mode':'off'}
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
    def test_login_required_and_csrf_rejected(self):
        import http.client
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request('GET','/api/status')
        r=conn.getresponse();self.assertEqual(r.status,401);r.read()
        conn.request('POST','/api/mode',body='{"mode":"on"}',headers={'Content-Type':'application/json'})
        r=conn.getresponse();self.assertEqual(r.status,403);r.read()
        conn.request('POST','/api/login',body='{"password":"test-password"}',headers={'Content-Type':'application/json','X-Luna':'1'})
        r=conn.getresponse();self.assertEqual(r.status,200);cookie=r.getheader('Set-Cookie');r.read()
        self.assertIn('HttpOnly',cookie)
        conn.request('GET','/api/status',headers={'Cookie':cookie.split(';')[0]})
        r=conn.getresponse();self.assertEqual(r.status,200);self.assertEqual(json.loads(r.read()),{'mode':'off'})
        self.server.app.action.assert_not_called()
        conn.close()
    def test_unknown_host_rejected(self):
        import http.client
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request('GET','/',headers={'Host':'attacker.invalid'})
        r=conn.getresponse();self.assertEqual(r.status,403);r.read();conn.close()
