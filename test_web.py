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
    def test_settings_live_without_resetting_mode_or_hold(self):
        self.app.mode='smart'
        self.app.until=1234
        journal=self.folder/'discharge-restore.json';journal.write_text('{"serial":"test","original_w":5000}')
        self.app.save_settings({'target_soc':75,'base_load_w':600})
        self.assertEqual(self.app.config()['target_soc'],75)
        self.assertEqual(self.app.mode,'smart');self.assertEqual(self.app.until,1234)
        self.assertTrue(journal.exists())
        with self.assertRaisesRegex(ValueError,'Geräteverbindung'):self.app.save_settings({'host':'192.0.2.1'})

    def test_active_process_accepts_only_changed_safe_fields(self):
        self.app.save_settings({});self.app.mode='smart';self.app.proc=Mock(poll=Mock(return_value=None));self.app.job='run'
        patch={k:v for k,v in self.app.config().items() if k!='mode'}
        patch['target_soc']=70
        self.app.save_settings(patch)
        self.assertEqual(self.app.config()['target_soc'],70)
        with self.assertRaises(ValueError):self.app.save_settings({'password':'different-device-password'})

    def test_external_controller_still_blocks_settings(self):
        import fcntl
        with (self.folder/'controller.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError,'externer'):self.app.save_settings({'base_load_w':600})
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
    def test_deadline_switches_off_without_browser(self):
        for mode in ('on','planned'):
            self.app.mode=mode
            self.app.until=0
            self.assertTrue(self.app.expire_order())
            self.assertEqual(self.app.mode,'off')
            self.assertIsNone(self.app.until)

    def test_unrelated_settings_keep_prices(self):
        self.app.price_data=[{'ct':12}]
        self.app.save_settings({})
        self.assertEqual(self.app.price_data,[{'ct':12}])
        self.app.save_settings({'tibber_token':'new-token'})
        self.assertEqual(self.app.price_data,[])

    def test_manual_still_obeys_soc_and_ac(self):
        c={**luna.DEFAULT,'_manual':True}
        s={'soc':61,'battery_status':2,'ac_charge_enabled':True}
        self.assertTrue(luna.decide(c,s,[],datetime.now(timezone.utc))[0])
        self.assertFalse(luna.decide(c,{**s,'soc':90},[],datetime.now(timezone.utc))[0])
        self.assertFalse(luna.decide(c,{**s,'ac_charge_enabled':False},[],datetime.now(timezone.utc))[0])
    def test_adopt_requires_successful_probe(self):
        self.app.device={'serial':'unconfirmed'}
        with self.assertRaises(ValueError):self.app.action('adopt-serial',{})

    def test_update_queues_preparation_while_smart(self):
        self.app.mode='smart'
        with patch('web.updater.inspect_repo'),patch('web.threading.Thread') as thread:
            self.app.action('update',{})
            self.assertTrue(self.app.update_preparing)
            self.assertEqual(self.app.update_status()['state'],'preparing')
            thread.return_value.start.assert_called_once()
            with self.assertRaisesRegex(ValueError,'Update'):self.app.action('mode',{'mode':'on'})

    def test_update_prepares_stop_and_release_before_start(self):
        self.app.save_settings({'expected_serial':'test','password':'test'})
        self.app.mode='smart';self.app.update_preparing=True
        luna.write_json(self.folder/'discharge-request.json',{'serial':'test','until':'2099-01-01T00:00:00+00:00'})
        with patch('web.subprocess.run',return_value=Mock(returncode=0,stdout='')) as run,patch('web.updater.start') as start:
            self.app.prepare_update()
            self.assertEqual([c.args[0][-2] for c in run.call_args_list],['stop','discharge-sync'])
            start.assert_called_once()
        self.assertEqual(self.app.mode,'off');self.assertFalse(self.app.update_preparing)
        self.assertIsNone(web.read(self.folder/'discharge-request.json',{})['until'])

    def test_update_stop_failure_never_installs(self):
        self.app.save_settings({'expected_serial':'test','password':'test'})
        self.app.mode='smart';self.app.update_preparing=True
        with patch('web.subprocess.run',return_value=Mock(returncode=1,stdout='')),patch('web.updater.start') as start:
            self.app.prepare_update();start.assert_not_called()
        self.assertEqual(self.app.mode,'off');self.assertEqual(self.app.update_status()['state'],'failed')
        self.assertFalse(self.app.update_preparing)

    def test_update_unresolved_restore_never_installs(self):
        self.app.save_settings({'expected_serial':'test','password':'test'})
        (self.folder/'discharge-restore.json').write_text('{}')
        with patch('web.subprocess.run',return_value=Mock(returncode=0,stdout='')),patch('web.updater.start') as start:
            self.app.prepare_update();start.assert_not_called()
        self.assertEqual(self.app.update_status()['state'],'failed')

    def test_update_idle_needs_no_device_io(self):
        with patch('web.subprocess.run') as run,patch('web.updater.start') as start:
            self.app.prepare_update();run.assert_not_called();start.assert_called_once()

    def test_update_blocks_controls_and_measurements(self):
        self.app.save_settings({})
        with patch('web.updater.busy',return_value=True),patch.object(self.app,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'Update'):self.app.action('mode',{'mode':'on'})
            self.app.request_sample(fast=True)
            launch.assert_not_called()

    def test_statistics_do_not_poll_in_background(self):
        self.app.save_settings({'statistics_enabled':True})
        with patch.object(self.app.closed,'wait',side_effect=[False,True]),patch.object(self.app,'launch') as launch,patch.object(self.app,'request_sample') as sample:
            self.app.worker()
            sample.assert_not_called();launch.assert_not_called()

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
    def test_pwa_assets_and_private_statistics(self):
        import http.client
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        for path,kind in [('/manifest.webmanifest','application/manifest+json'),('/sw.js','application/javascript'),('/icon-192.png','image/png')]:
            conn.request('GET',path);r=conn.getresponse()
            self.assertEqual(r.status,200);self.assertIn(kind,r.getheader('Content-Type'));self.assertTrue(r.read())
        for path in ('/api/history','/api/update','/api/journal','/api/journal/export','/api/journal/text','/api/journal/plan?id=1'):
            conn.request('GET',path);r=conn.getresponse();self.assertEqual(r.status,401);r.read()
        conn.request('GET','/healthz');r=conn.getresponse();self.assertEqual(r.status,200)
        self.assertEqual(set(json.loads(r.read())),{'ok','pid','revision'})
        self.server.app.request_sample.assert_not_called();conn.close()

    def test_journal_reads_exports_and_validation_without_measurements(self):
        import http.client,gzip
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request('POST','/api/login',body='{"password":"test-password"}',headers={'Content-Type':'application/json','X-Luna':'1'})
        r=conn.getresponse();cookie=r.getheader('Set-Cookie').split(';')[0];r.read()
        self.server.app.journal.entries.return_value={'events':[]}
        import io
        from contextlib import contextmanager
        @contextmanager
        def download(*args):yield io.BytesIO(gzip.compress(b'{"plans":{},"events":[]}'))
        self.server.app.journal.download.side_effect=download
        self.server.app.config.return_value={'timezone':'Europe/Berlin'}
        self.server.app.journal.plan.return_value={'config':{}}
        for path in ('/api/journal?hours=12','/api/journal/plan?id=1'):
            conn.request('GET',path,headers={'Cookie':cookie});r=conn.getresponse();self.assertEqual(r.status,200);r.read()
        conn.request('GET','/api/journal/export?hours=24',headers={'Cookie':cookie})
        r=conn.getresponse();self.assertEqual(r.status,200);self.assertIn('attachment',r.getheader('Content-Disposition'));self.assertEqual(json.loads(gzip.decompress(r.read())),{'plans':{},'events':[]})
        conn.request('GET','/api/journal?hours=999',headers={'Cookie':cookie});r=conn.getresponse();self.assertEqual(r.status,400);r.read()
        self.server.app.request_sample.assert_not_called();self.server.app.action.assert_not_called();conn.close()

    def test_postcode_lookup_requires_login_and_does_not_touch_controller(self):
        import http.client
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        headers={'Content-Type':'application/json','X-Luna':'1'}
        with patch('geocoding.lookup',return_value=[{'name':'Berlin','latitude':52.5,'longitude':13.4,'postcode':'10115'}]) as lookup:
            conn.request('POST','/api/pv-location',body='{"postcode":"10115"}',headers=headers)
            r=conn.getresponse();self.assertEqual(r.status,401);r.read();lookup.assert_not_called()
            conn.request('POST','/api/login',body='{"password":"test-password"}',headers=headers)
            r=conn.getresponse();self.assertEqual(r.status,200);headers['Cookie']=r.getheader('Set-Cookie').split(';')[0];r.read()
            conn.request('POST','/api/pv-location',body='{"postcode":"10115"}',headers=headers)
            r=conn.getresponse();self.assertEqual(r.status,200);self.assertEqual(json.loads(r.read())['results'][0]['name'],'Berlin')
            lookup.assert_called_once_with('10115')
            self.server.app.action.assert_not_called();self.server.app.request_sample.assert_not_called()
        conn.close()

    def test_unknown_host_rejected(self):
        import http.client
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request('GET','/',headers={'Host':'attacker.invalid'})
        r=conn.getresponse();self.assertEqual(r.status,403);r.read();conn.close()

class PlannedTests(unittest.TestCase):
    def setUp(self):
        self.c = dict(luna.DEFAULT)
        self.now = datetime(2026,10,23,18,tzinfo=timezone.utc)
        self.data = {'start':'2026-10-23T23:30','end_kind':'time','end':'01:00'}
    def test_overnight(self):
        p=web.planned_order(self.data,self.c,self.now)
        self.assertEqual((datetime.fromisoformat(p['end'])-datetime.fromisoformat(p['start'])).total_seconds(),5400)
    def test_soc_has_hard_deadline(self):
        p=web.planned_order({**self.data,'end_kind':'soc','target_soc':75},self.c,self.now)
        self.assertEqual(p['target_soc'],75)
        self.assertEqual((datetime.fromisoformat(p['end'])-datetime.fromisoformat(p['start'])).total_seconds(),self.c['max_session_minutes']*60)
        self.assertEqual(self.c['target_soc'],luna.DEFAULT['target_soc'])
    def test_invalid_and_dst(self):
        for patch in [{'start':'2026-10-23T12:00'}, {'end':'06:00'}, {'end_kind':'soc','target_soc':float('nan')}, {'start':'2026-10-25T02:30'}]:
            with self.assertRaises(ValueError):web.planned_order({**self.data,**patch},self.c,self.now)
    def test_start_once_expire_and_no_restart(self):
        with tempfile.TemporaryDirectory() as d:
            app=web.Dashboard(Path(d),start_worker=False)
            app.planned=web.planned_order(self.data,self.c,self.now)
            app.mode='planned'
            start=datetime.fromisoformat(app.planned['start'])
            end=datetime.fromisoformat(app.planned['end'])
            with patch.object(app,'preflight'),patch.object(app,'launch') as launch:
                app.tick_planned(self.now)
                launch.assert_not_called()
                app.tick_planned(start)
                app.tick_planned(start)
                launch.assert_called_once_with('charge',target_soc=self.c['target_soc'])
                app.tick_planned(end)
                self.assertEqual(app.mode,'off')
                self.assertIsNone(app.planned)
            self.assertIsNone(web.Dashboard(Path(d),start_worker=False).planned)
    def test_missed_window_does_not_launch(self):
        with tempfile.TemporaryDirectory() as d:
            app=web.Dashboard(Path(d),start_worker=False)
            app.planned=web.planned_order(self.data,self.c,self.now)
            app.mode='planned'
            with patch.object(app,'launch') as launch:
                app.tick_planned(datetime.fromisoformat(app.planned['end']))
                launch.assert_not_called()
                self.assertEqual(app.mode,'off')

class PriceComparisonTests(unittest.TestCase):
    def prices(self,start,hours):
        from datetime import timedelta
        return [{'start':start+timedelta(minutes=15*i),'end':start+timedelta(minutes=15*(i+1)),'ct':10 if i<24 else 30} for i in range(hours*4)]
    def test_full_day_and_losses(self):
        c=dict(luna.DEFAULT);c['timezone']='UTC'
        p=self.prices(datetime(2026,10,24,tzinfo=timezone.utc),24)
        r=web.next_day_comparison(c,p,datetime(2026,10,23,tzinfo=timezone.utc))
        self.assertEqual(r['day_ct'],25)
        self.assertEqual(r['night_ct'],10)
        self.assertAlmostEqual(r['saving_ct'],25-10/.85)
    def test_gap_is_not_average(self):
        c=dict(luna.DEFAULT);c['timezone']='UTC'
        p=self.prices(datetime(2026,10,24,tzinfo=timezone.utc),24)
        del p[30]
        r=web.next_day_comparison(c,p,datetime(2026,10,23,tzinfo=timezone.utc))
        self.assertFalse(r['complete']);self.assertIsNone(r['saving_ct'])
    def test_dst_25_hour_day_and_negative_prices(self):
        c=dict(luna.DEFAULT)
        p=self.prices(datetime(2026,10,24,22,tzinfo=timezone.utc),25)
        for row in p:row['ct']=-5
        r=web.next_day_comparison(c,p,datetime(2026,10,24,12,tzinfo=timezone.utc))
        self.assertTrue(r['complete']);self.assertEqual(r['day_ct'],-5)
    def test_empty_prices(self):
        r=web.next_day_comparison(dict(luna.DEFAULT),[],datetime.now(timezone.utc))
        self.assertFalse(r['complete']);self.assertIsNone(r['night_ct'])

class ComparisonDateTests(unittest.TestCase):
    def test_after_midnight_uses_today_during_night(self):
        from datetime import timedelta
        with tempfile.TemporaryDirectory() as folder:
            app=web.Dashboard(Path(folder),start_worker=False)
            start=datetime(2026,10,23,22,tzinfo=timezone.utc)
            app.price_data=[{'start':start+timedelta(minutes=15*i),'end':start+timedelta(minutes=15*(i+1)),'ct':20} for i in range(96)]
            import time
            app.price_at=time.monotonic()
            with patch('web.datetime',wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,10,23,23,tzinfo=timezone.utc)
                status=app.snapshot()
            self.assertEqual(status['comparison']['date'],'2026-10-24')
            self.assertTrue(status['comparison']['complete'])
            self.assertFalse(status['comparisons']['tomorrow']['complete'])
    def test_after_night_selects_next_day(self):
        with tempfile.TemporaryDirectory() as folder:
            app=web.Dashboard(Path(folder),start_worker=False)
            with patch('web.datetime',wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,10,24,10,tzinfo=timezone.utc)
                status=app.snapshot()
            self.assertEqual(status['comparison']['date'],'2026-10-25')

class SmartPreviewTests(unittest.TestCase):
    def test_stale_soc_blocks_preview(self):
        from datetime import timedelta
        c={**luna.DEFAULT,'battery_capacity_kwh':10}
        now=datetime(2026,10,24,1,tzinfo=timezone.utc)
        p=web.smart_preview(c,[],now,{'soc':30,'time':(now-timedelta(minutes=3)).isoformat()})
        self.assertEqual(p['windows'],[])
        self.assertIn('Akkustand',p['reason'])

class SessionPersistenceTests(unittest.TestCase):
    def test_persistence_expiry_password_change_and_revoke(self):
        from types import SimpleNamespace
        import time
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'web-sessions.json'
            token='browser-session-secret'
            key=web.session_key(token)
            server=SimpleNamespace(session_path=path,auth={'hash':'password-hash'},sessions={key:time.time()+1000,'expired':1})
            web.save_sessions(server)
            self.assertNotIn(token,path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertIn(key,web.load_sessions(path,server.auth))
            self.assertNotIn('expired',web.load_sessions(path,server.auth))
            self.assertEqual(web.load_sessions(path,{'hash':'new-password'}),{})
            server.sessions.pop(key)
            web.save_sessions(server)
            self.assertNotIn(key,web.load_sessions(path,server.auth))

class DisplaySamplingTests(unittest.TestCase):
    def test_rate_limit_and_running_controller_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            app=web.Dashboard(Path(folder),start_worker=False)
            app.save_settings({})
            with patch.object(app,'launch') as launch,patch('web.time.monotonic',return_value=100):
                app.request_sample()
                app.request_sample()
                launch.assert_called_once_with('sample')
            with patch.object(app,'launch') as launch,patch('web.time.monotonic',return_value=111):
                app.request_sample()
                launch.assert_not_called()
                app.request_sample(fast=True)
                launch.assert_called_once_with('sample')
            app.proc=object()
            with patch.object(app,'launch') as launch,patch('web.time.monotonic',return_value=500):
                app.request_sample(fast=True)
                launch.assert_not_called()
