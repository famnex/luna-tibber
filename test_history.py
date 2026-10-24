import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
import luna
from history import History

class PlanHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.h=History(self.folder);self.now=datetime(2026,10,24,tzinfo=timezone.utc)
        self.c={**luna.DEFAULT,'timezone':'UTC','roundtrip_efficiency':1}
        self.prices=[{'start':self.now+timedelta(minutes=15*i),'end':self.now+timedelta(minutes=15*(i+1)),'ct':10 if i<24 else 30} for i in range(96)]
    def tearDown(self):self.tmp.cleanup()
    def command(self,seconds=0,watts=1000,minutes=2):
        self.h.record(self.c,{'event':'charge_command','time':(self.now+timedelta(seconds=seconds)).isoformat(),'watts':watts,'minutes':minutes},self.prices)
    def today(self,seconds=300):return self.h.summary(self.c,self.now+timedelta(seconds=seconds))['periods']['today']
    def test_power_time_and_price_model(self):
        self.command();result=self.today()
        self.assertAlmostEqual(result['charge'],1/30)
        self.assertAlmostEqual(result['saving'],(1/30)*.2)
        self.assertEqual(self.today(60)['seconds'],60)
    def test_overlapping_renewals_and_duplicates(self):
        self.command();self.command(90);self.command(90)
        self.assertEqual(self.today()['seconds'],210)
        self.assertAlmostEqual(self.today()['charge'],210/3600)
    def test_stop_shortens_and_survives_restart(self):
        self.command();self.h.finish(self.now+timedelta(seconds=30))
        self.h=History(self.folder)
        self.assertEqual(self.today()['seconds'],30)
    def test_snapshots_do_not_record_anything(self):
        self.h.record(self.c,{'event':'snapshot','time':self.now.isoformat(),'soc':60,'battery_power_w':5000},self.prices)
        self.assertEqual(self.today()['seconds'],0)
    def test_missing_prices_are_unvalued(self):
        self.prices=[];self.command()
        self.assertEqual(self.today()['valued'],0)
        self.assertGreater(self.today()['charge'],0)
    def test_negative_values_and_losses(self):
        self.prices[0]['ct']=40;self.c['roundtrip_efficiency']=.81
        self.command();r=self.today()
        self.assertAlmostEqual(r['discharge'],(1/30)*.9)
        self.assertLess(r['saving'],0)
    def test_midnight_and_grouping(self):
        self.now=datetime(2026,10,24,23,59,30,tzinfo=timezone.utc)
        self.command();r=self.h.summary(self.c,self.now+timedelta(minutes=3))
        self.assertEqual(r['periods']['yesterday']['seconds'],30)
        self.assertEqual(r['periods']['today']['seconds'],90)
        self.assertEqual(r['months'][0]['seconds'],120)
        self.assertEqual(r['years'][0]['period'],'2026')
    def test_previous_measurements_are_not_mixed(self):
        old=self.folder/'history.sqlite3';old.write_text('legacy')
        h=History(self.folder);self.assertEqual(old.read_text(),'legacy')
        self.assertEqual(h.summary(self.c,self.now)['source'],'plan')
    def test_disabled_and_future_commands(self):
        self.c['statistics_enabled']=False;self.command()
        self.assertEqual(self.today()['seconds'],0)
        self.c['statistics_enabled']=True;self.command(3600)
        self.assertEqual(self.today()['seconds'],0)
