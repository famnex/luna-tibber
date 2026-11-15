import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from whatsapp import WhatsApp,send_message,NoRedirect
from car_notifications import alerts,CarNotifier

class WhatsAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.w=WhatsApp(self.folder,start_worker=False)
    def add(self,phone='+491701234567',key='123456'):
        return self.w.change('save',{'name':'Test','phone':phone,'key':key,'authorized':True})['recipients'][-1]['id']
    def process(self):
        self.w.process(self.w.queue.get_nowait())
    def test_multiple_recipients_private_keys_and_reload(self):
        self.add();self.add('+491701234568','654321')
        public=json.dumps(self.w.status());self.assertNotIn('"key":',public);self.assertNotIn('654321',public)
        self.assertEqual(len(WhatsApp(self.folder,False).status()['recipients']),2)
        self.assertEqual(self.w.path.stat().st_mode&0o777,0o600)
    def test_validate_duplicate_and_changed_number_key(self):
        rid=self.add()
        with self.assertRaises(ValueError):self.add()
        with self.assertRaises(ValueError):self.add('localhost')
        with self.assertRaises(ValueError):self.w.change('save',{'id':rid,'phone':'+491701234568','key':'','authorized':True})
        self.w.change('save',{'id':rid,'name':'Neu','phone':'+491701234567','key':''})
        self.assertEqual(self.w.data['recipients'][0]['key'],'123456')
    def test_test_is_targeted_and_deduplicated(self):
        a=self.add();self.add('+491701234568','654321');self.w.sender=Mock()
        self.w.test(a)
        with self.assertRaises(ValueError):self.w.test(a)
        self.process();self.w.sender.assert_called_once()
        self.assertEqual(self.w.sender.call_args.args[0],'+491701234567')
        self.assertEqual(self.w.status()['recipients'][0]['delivery']['state'],'accepted')
    def test_fanout_disabled_and_success_persist(self):
        a=self.add();b=self.add('+491701234568','654321');self.w.sender=Mock()
        self.assertEqual(self.w.emit('need','Titel','Bedarf'),2)
        self.assertEqual(self.w.emit('need','Titel','Bedarf'),0)
        self.process();self.process()
        self.assertEqual(WhatsApp(self.folder,False).emit('need','Titel','Bedarf'),0)
        self.w.change('settings',{'car_alerts':False})
        self.assertEqual(self.w.emit('need2','Titel','Bedarf'),0)
        self.assertEqual(self.w.emit('sys','Titel','Fehler','system'),0)
    def test_deleted_or_disabled_queue_not_delivered(self):
        rid=self.add();self.w.sender=Mock();self.w.emit('need','Titel','Bedarf')
        self.w.change('delete',{'id':rid});self.process();self.w.sender.assert_not_called()
        self.add();self.w.emit('other','Titel','Bedarf');self.w.change('settings',{'car_alerts':False});self.process();self.w.sender.assert_not_called()
    def test_failed_delivery_is_not_success_and_secret_never_exposed(self):
        rid=self.add();self.w.sender=Mock(side_effect=RuntimeError('private key 123456 url'))
        self.w.test(rid);self.process()
        self.assertEqual(self.w.status()['recipients'][0]['delivery']['state'],'failed')
        self.assertNotIn('private key',json.dumps(self.w.status()))
        self.assertFalse(any(v.get('success') for v in self.w.events.values()))
    def test_provider_response_and_fixed_url(self):
        for body,ok in [(b'Message queued.',True),(b'ERROR: invalid key',False),(b'<html>unknown response</html>',False)]:
            response=Mock();response.status=200;response.read.return_value=body
            manager=Mock();manager.__enter__=Mock(return_value=response);manager.__exit__=Mock(return_value=False)
            opener=Mock();opener.open.return_value=manager
            with patch('whatsapp.urllib.request.build_opener',return_value=opener):
                if ok:send_message('+491701234567','123456','Hallo & ä')
                else:
                    with self.assertRaises(ValueError):send_message('+491701234567','123456','Hallo & ä')
                url=opener.open.call_args.args[0].full_url
                self.assertTrue(url.startswith('https://api.callmebot.com/whatsapp.php?'))
                self.assertIn('Hallo+%26+%C3%A4',url)
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://evil.test'))

class CarAlertTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,15,12,tzinfo=timezone.utc)
        self.car={'id':'a','name':'Born','soc':20,'target_soc':60,'missing_kwh':20,'deadline':(self.now+timedelta(hours=18)).isoformat(),'connector_status':'disconnected','connected':False}
        self.advice={'vehicles':[self.car,{'id':'b','name':'ID.3','connected':True}],'priority':'a'}
    def test_wrong_car_and_distances(self):
        a=alerts(self.advice,self.now)[0]
        self.assertEqual(a['title'],'LUNA · Born');self.assertIn('ID.3 ist angesteckt',a['body']);self.assertIn('20 kWh',a['body']);self.assertIn('60 %',a['body'])
    def test_no_warning_outside_horizon_or_without_advice(self):
        self.car['deadline']=(self.now+timedelta(hours=25)).isoformat()
        self.assertEqual(alerts(self.advice,self.now),[]);self.assertEqual(alerts({'vehicles':[]},self.now),[])
    def test_urgency_stable_and_currently_charging(self):
        self.car.update(charging_status='charging',connected=True,connector_status='connected')
        self.assertEqual(alerts(self.advice,self.now),[])
        self.car['deadline']=(self.now+timedelta(hours=2)).isoformat()
        a=alerts(self.advice,self.now)[0];self.assertIn('urgent',a['key']);self.assertNotIn('anschließen',a['title'])
        self.car['target_soc']=61;self.assertEqual(alerts(self.advice,self.now)[0]['key'],a['key'])
    def test_unknown_connector_not_claimed_disconnected(self):
        self.car['connector_status']='unknown'
        self.assertNotIn('anschließen',alerts(self.advice,self.now)[0]['title'])
    def test_background_requires_two_checks_and_uses_both_channels(self):
        app=SimpleNamespace(whatsapp=Mock(),notifications=Mock(),config=lambda:{'timezone':'Europe/Berlin','push_contact':'x@y.z'},car_planning=Mock(),vehicle_probe=SimpleNamespace(cache={}),car_context=Mock())
        app.whatsapp.status.return_value={'car_alerts':True};monitor=CarNotifier(app)
        with patch('car_planning.advice',return_value=self.advice):
            monitor.tick(self.now);app.whatsapp.emit.assert_not_called()
            monitor.tick(self.now+timedelta(seconds=60));app.whatsapp.emit.assert_called_once();app.notifications.emit.assert_called_once()
        with patch('car_planning.advice',return_value={'vehicles':[]}):monitor.tick(self.now+timedelta(seconds=120))
        self.assertEqual(monitor.seen,{})
