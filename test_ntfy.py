import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
from datetime import datetime,timedelta,timezone
from ntfy import Ntfy,send_message
from car_notifications import CarNotifier

class NtfyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name);self.n=Ntfy(self.folder,False)
    def add(self,topic='',key=''):
        return self.n.change('save',{'name':'Handys','topic':topic,'key':key})['recipients'][-1]
    def test_random_topic_persistence_and_validation(self):
        row=self.add();self.assertRegex(row['topic'],r'^luna-[0-9a-f]{32}$')
        self.assertEqual(Ntfy(self.folder,False).status()['recipients'][0]['topic'],row['topic'])
        for topic in ('../bad','x/y','a?token=secret','app','x'*65):
            with self.assertRaises(ValueError):self.add(topic)
        with self.assertRaises(ValueError):self.add(row['topic'])
        self.assertEqual(self.n.path.stat().st_mode&0o777,0o600)
    def test_token_private_and_keep_clear(self):
        row=self.add('my-private-topic','tk_testsecret123456')
        self.assertNotIn('tk_testsecret123456',json.dumps(self.n.status()))
        self.n.change('save',{**row,'key':''});self.assertEqual(self.n.data['recipients'][0]['key'],'tk_testsecret123456')
        self.n.change('save',{**row,'key':'','clear_key':True});self.assertEqual(self.n.data['recipients'][0]['key'],'')
    def test_multiple_targets_test_and_dedup(self):
        a=self.add();b=self.add();self.n.sender=Mock();self.n.test(a['id'])
        self.n.process(self.n.queue.get_nowait());self.n.sender.assert_called_once()
        self.assertEqual(self.n.sender.call_args.args[0],a['topic'])
        self.assertIn('ntfy-Test',self.n.sender.call_args.args[2])
        self.assertEqual(self.n.emit('ev:car','Auto laden','Bedarf'),2)
        self.assertEqual(self.n.emit('ev:car','Auto laden','Bedarf'),0)
        self.n.change('delete',{'id':a['id']});self.n.process(self.n.queue.get_nowait());self.n.sender.assert_called_once()
        self.n.process(self.n.queue.get_nowait());self.assertEqual(self.n.sender.call_count,2)
        self.assertIn('ntfy angenommen',self.n.status()['recipients'][0]['delivery']['message'])
    def test_http_json_and_bearer_without_redirect(self):
        response=Mock(status=200);response.read.return_value=b'{"id":"abc","event":"message","topic":"test"}'
        manager=Mock();manager.__enter__=Mock(return_value=response);manager.__exit__=Mock(return_value=False);opener=Mock();opener.open.return_value=manager
        with patch('ntfy.urllib.request.build_opener',return_value=opener):
            send_message('test','tk_secret1234','LUNA · Lädt\nNoch 5 kWh')
            request=opener.open.call_args.args[0]
            self.assertEqual(request.full_url,'https://ntfy.sh/');self.assertEqual(request.get_header('Authorization'),'Bearer tk_secret1234')
            self.assertEqual(json.loads(request.data)['title'],'LUNA · Lädt')
            self.assertNotIn(b'tk_secret',request.data)
            response.read.return_value=b'{"error":"no access"}'
            with self.assertRaises(ValueError):send_message('test','','title\nbody')
    def test_ntfy_auto_alerts_independent_of_whatsapp(self):
        now=datetime(2026,11,15,12,tzinfo=timezone.utc)
        app=SimpleNamespace(ntfy=self.n,whatsapp=Mock(),notifications=Mock(),config=lambda:{'timezone':'Europe/Berlin'},car_planning=Mock(),vehicle_probe=SimpleNamespace(cache={}),car_context=Mock())
        app.whatsapp.status.return_value={'car_alerts':False};self.add();monitor=CarNotifier(app)
        advice={'priority':'a','vehicles':[{'id':'a','name':'Born','soc':20,'deadline':(now+timedelta(hours=2)).isoformat(),'target_soc':40,'missing_kwh':10,'connected':False,'connector_status':'disconnected'}]}
        with patch('car_planning.advice',return_value=advice):
            monitor.tick(now);self.assertEqual(self.n.queue.qsize(),0)
            monitor.tick(now+timedelta(seconds=60));self.assertEqual(self.n.queue.qsize(),1)
            app.notifications.emit.assert_not_called()
        self.n.change('settings',{'car_alerts':False});self.n.sender=Mock();self.n.process(self.n.queue.get_nowait());self.n.sender.assert_not_called()
