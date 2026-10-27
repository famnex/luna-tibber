import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from audit import Journal

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name);self.log=Journal(self.folder)
        self.c={'timezone':'Europe/Berlin','password':'secret-pass-123','tibber_token':'secret-token-123','host':'192.0.2.9'}
        self.now=datetime.now(timezone.utc)
    def tearDown(self):self.tmp.cleanup()
    def event(self,**extra):
        return {'event':'decision','time':self.now.isoformat(),'live':True,'soc':40,'battery_power_w':-500,'eligible':False,'reason':'Warte auf günstigen Abschnitt',
                'dispatch':{'hold':False,'reason':'Hausverbrauch freigegeben','guard':{'threshold_soc':30,'required_kwh':2.5,'surplus_kwh':1}},
                'diagnostic_plan':{'planned_kwh':2,'effective_target_soc':50,'windows':[],'joint':{'bridge':{'required_soc':30}}},**extra}
    def test_prose_measurement_and_command_are_distinct_and_persist(self):
        self.log.record(self.c,self.event(),'smart','run','revision')
        self.log.record(self.c,{'event':'charge_command','time':self.now.isoformat(),'watts':1000,'minutes':2},'smart')
        log=Journal(self.folder);d=log.export()
        self.assertEqual(len(d['events']),2)
        self.assertIn('entlädt',d['events'][0]['text']);self.assertIn('Ladebefehl gesendet',d['events'][1]['text'])
        self.assertEqual(d['events'][0]['data']['soc'],40)
        self.assertTrue(d['plans']);self.assertIn('Vollständige Planstände',log.prose())
    def test_all_decisions_stored_but_identical_checks_hidden(self):
        self.log.record(self.c,self.event(),'smart')
        self.log.record(self.c,self.event(time=(self.now+timedelta(seconds=10)).isoformat()),'smart')
        self.assertEqual(len(self.log.entries()['events']),1)
        self.assertEqual(len(self.log.entries(all_checks=True)['events']),2)
        self.assertEqual(len(self.log.export()['plans']),1)
        self.log.record(self.c,self.event(battery_power_w=600),'smart')
        self.assertEqual(len(self.log.entries()['events']),2)
    def test_no_secrets_in_prose_export_or_plans(self):
        e=self.event(reason='secret-pass-123 secret-token-123 192.0.2.9',password='secret-pass-123',diagnostic_inputs={**self.c,'base_load_w':700})
        self.log.record(self.c,e)
        text=json.dumps(self.log.export())+self.log.prose()
        for value in self.c.values():
            if value!='Europe/Berlin':self.assertNotIn(value,text)
        plan=next(iter(self.log.export()['plans'].values()))
        self.assertEqual(plan['config']['base_load_w'],700)
    def test_changed_plan_snapshot_and_lookup(self):
        self.log.record(self.c,self.event())
        self.log.record(self.c,self.event(diagnostic_plan={'planned_kwh':3,'windows':[]}))
        self.assertEqual(len(self.log.export()['plans']),2)
        last=self.log.entries(all_checks=True)['events'][0]
        self.assertEqual(self.log.plan(last['plan_id'])['charging']['planned_kwh'],3)
    def test_retention_and_pagination(self):
        old=self.now-timedelta(days=8)
        self.log.record(self.c,self.event(time=old.isoformat()))
        for i in range(205):self.log.record(self.c,{'event':'stopped','time':self.now.isoformat()})
        first=self.log.entries();self.assertEqual(len(first['events']),200);self.assertIsNotNone(first['before'])
        second=self.log.entries(before=first['before']);self.assertEqual(len(second['events']),5)
        with self.log.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],205)
    def test_errors_do_not_interrupt_controller(self):
        self.log.path=self.folder/'missing'/'db'
        self.log.record(self.c,self.event())
        self.assertTrue(self.log.error)
    def test_simulation_is_explicit(self):
        self.log.record(self.c,self.event(live=False))
        self.assertIn('Nur Simulation',self.log.entries()['events'][0]['text'])

    def test_dst_prose_disambiguates_repeated_hour(self):
        for hour in (0,1):
            self.log.record(self.c,self.event(time=datetime(2026,10,25,hour,30,tzinfo=timezone.utc).isoformat()))
        from unittest.mock import patch
        with patch('audit.datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,10,26,tzinfo=timezone.utc)
            text=self.log.prose(48)
        self.assertIn('02:30:00+02:00',text);self.assertIn('02:30:00+01:00',text)

    def test_retired_controller_stop_event_is_not_lost(self):
        import web,luna
        from unittest.mock import Mock
        app=web.Dashboard(self.folder,start_worker=False)
        app.generation=5
        proc=Mock(stdout=[json.dumps({'event':'stopped_on_exit','time':self.now.isoformat()})])
        proc.wait.return_value=0
        app.collect(proc,4,'run','smart')
        events=app.journal.entries()['events']
        self.assertTrue(any(e['event']=='stopped_on_exit' and e['mode']=='smart' for e in events))

class DownloadTests(unittest.TestCase):
    def test_streamed_download_matches_export_and_text_skips_plans(self):
        import gzip,json,tempfile
        from unittest.mock import patch
        from audit import Journal
        with tempfile.TemporaryDirectory() as folder:
            j=Journal(Path(folder))
            j.record({}, {'event':'decision','soc':42,'diagnostic_plan':{'needed_kwh':3}})
            expected=j.export()
            with j.download() as f:actual=json.loads(gzip.decompress(f.read()))
            self.assertEqual(actual['events'],expected['events']);self.assertEqual(actual['plans'],expected['plans'])
            with patch.object(j,'plan',side_effect=AssertionError('TXT must not decode plans')):
                with j.download(compressed=False) as f:self.assertIn('42',f.read().decode())
            with j.download() as f:
                with self.assertRaises(ValueError):
                    with j.download():pass
            with j.download() as f:self.assertTrue(f.read())
