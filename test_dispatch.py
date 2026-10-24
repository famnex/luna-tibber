import unittest
from datetime import datetime,timedelta,timezone
import luna
from dispatch import plan

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.c={**luna.DEFAULT,'smart_discharge_enabled':True,'battery_capacity_kwh':10,'base_load_w':500,'reserve_soc':20,'roundtrip_efficiency':1,'min_saving_ct_kwh':2}
        self.now=datetime(2026,10,24,10,tzinfo=timezone.utc) # noon local, 12 h until next night
        self.prices=[{'start':self.now+timedelta(hours=i),'end':self.now+timedelta(hours=i+1),'ct':50 if i in (6,7) else 20} for i in range(12)]
    def test_reserves_for_evening_and_releases_then(self):
        p=plan(self.c,self.prices,self.now,30) # 1 kWh, two expensive hours
        self.assertTrue(p['hold'])
        releases=[w for w in p['windows'] if w['action']=='discharge']
        self.assertEqual([w['ct'] for w in releases],[50,50])
        self.assertFalse(plan(self.c,self.prices,self.now+timedelta(hours=6),30)['hold'])
    def test_more_energy_and_dynamic_soc(self):
        self.assertFalse(plan(self.c,self.prices,self.now,90)['hold'])
        self.assertTrue(plan(self.c,self.prices,self.now,20)['hold'])
    def test_incomplete_prices_release_and_disabled(self):
        p=plan(self.c,self.prices[:-1],self.now,30)
        self.assertFalse(p['complete']);self.assertFalse(p['hold'])
        self.assertFalse(plan({**self.c,'smart_discharge_enabled':False},self.prices,self.now,30)['hold'])
    def test_no_measurement_and_no_load(self):
        for soc in (None,float('nan'),101):self.assertFalse(plan(self.c,self.prices,self.now,soc)['hold'])
        self.assertFalse(plan({**self.c,'base_load_w':0},self.prices,self.now,30)['hold'])
    def test_night_reserve_and_dst(self):
        now=datetime(2026,10,25,0,tzinfo=timezone.utc)
        p=plan(self.c,[],now,60)
        self.assertTrue(p['hold'])
        self.assertEqual(datetime.fromisoformat(p['windows'][0]['end']),datetime(2026,10,25,5,tzinfo=timezone.utc))
    def test_energy_conservation(self):
        p=plan(self.c,self.prices,self.now,27)
        kwh=sum((datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])).total_seconds()/3600*.5 for w in p['windows'] if w['action']=='discharge')
        self.assertAlmostEqual(kwh,.7)
    def test_charge_economics_uses_evening_slots(self):
        c={**self.c,'timezone':'UTC','target_soc':30}
        now=datetime(2026,10,24,tzinfo=timezone.utc)
        rows=[{'start':now+timedelta(hours=i),'end':now+timedelta(hours=i+1),'ct':15 if i<6 else 50 if i in (18,19) else 10} for i in range(24)]
        p=luna.economics_plan(c,rows,now)
        self.assertTrue(p['ok']);self.assertEqual(p['reference_ct_kwh'],50)
