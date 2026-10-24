import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
import luna
from history import History

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.h=History(self.folder);self.now=datetime(2026,10,24,10,tzinfo=timezone.utc)
        self.c={**luna.DEFAULT,'battery_capacity_kwh':10,'roundtrip_efficiency':1}
        self.prices=[{'start':self.now,'end':self.now+timedelta(minutes=2),'ct':10},
                     {'start':self.now+timedelta(minutes=2),'end':self.now+timedelta(hours=2),'ct':30}]
    def tearDown(self):self.tmp.cleanup()
    def sample(self,minutes,power,soc,app=True,pv=0):
        self.h.record(self.c,{'time':(self.now+timedelta(minutes=minutes)).isoformat(),'soc':soc,'battery_power_w':power,'pv_input_w':pv,'app_charging':app},self.prices)
    def test_cost_attributed_only_when_energy_used(self):
        self.sample(0,600,0);self.sample(1,600,.1)
        s=self.h.summary(self.c,self.now)['periods']['today']
        self.assertEqual(s['saving'],0);self.assertAlmostEqual(s['charge'],.01)
        self.sample(2,-600,.1,False);self.sample(3,-600,0,False)
        s=self.h.summary(self.c,self.now)['periods']['today']
        self.assertAlmostEqual(s['valued'],.01);self.assertAlmostEqual(s['saving'],.002)
        self.assertAlmostEqual(s['cost'],.001)
    def test_solar_and_unknown_stock_not_credited(self):
        self.sample(0,600,50,pv=1000);self.sample(1,600,50.1,pv=1000)
        self.sample(2,-600,50.1,False);self.sample(3,-600,50,False)
        self.assertEqual(self.h.summary(self.c,self.now)['periods']['today']['valued'],0)
    def test_gap_and_restart(self):
        self.sample(0,600,0);self.sample(1,600,.1)
        self.h=History(self.folder)
        self.sample(10,-600,.1,False);self.sample(11,-600,0,False)
        s=self.h.summary(self.c,self.now)['periods']['today']
        self.assertEqual(s['valued'],0);self.assertEqual(s['gaps'],540)
    def test_negative_savings_and_grouping(self):
        self.prices[0]['ct']=50
        self.sample(0,600,0);self.sample(1,600,.1);self.sample(2,-600,.1,False);self.sample(3,-600,0,False)
        data=self.h.summary(self.c,self.now)
        self.assertLess(data['periods']['today']['saving'],0)
        self.assertEqual(data['months'][0]['period'],'2026-10')
        self.assertEqual(data['years'][0]['saving'],data['periods']['today']['saving'])
    def test_no_double_counting(self):
        self.sample(0,600,0);self.sample(1,600,.1);self.sample(1,600,.1)
        self.assertEqual(self.h.summary(self.c,self.now)['periods']['today']['seconds'],60)
    def test_midnight_split_and_loss_model(self):
        self.now=datetime(2026,10,24,21,59,30,tzinfo=timezone.utc)
        self.prices=[{'start':self.now,'end':self.now+timedelta(hours=1),'ct':20}]
        self.sample(0,600,0);self.sample(1,600,.1)
        now=self.now+timedelta(minutes=1)
        result=self.h.summary(self.c,now)
        self.assertEqual(result['periods']['today']['seconds'],30)
        self.assertEqual(result['periods']['yesterday']['seconds'],30)
