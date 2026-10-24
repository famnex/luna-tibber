import math
import unittest
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import luna,smart,dispatch,joint

class JointTests(unittest.TestCase):
    def setup_case(self, hour=0, soc=0):
        a=datetime(2026,10,24,tzinfo=timezone.utc)
        c={**luna.DEFAULT,'timezone':'UTC','pv_enabled':True,'smart_discharge_enabled':True,
           'battery_capacity_kwh':10,'target_soc':80,'base_load_w':500,
           'charge_power_w':5000,'roundtrip_efficiency':.81,'wear_ct_kwh':0,'min_saving_ct_kwh':0}
        c['_pv']={'rows':[{'start':a+timedelta(hours=i),'end':a+timedelta(hours=i+1),'kw':4 if 10<=i%24<15 else 0} for i in range(72)]}
        prices=[{'start':a+timedelta(minutes=i*15),'end':a+timedelta(minutes=(i+1)*15),'ct':10 if i%96<24 else 40} for i in range(192)]
        return c,prices,a+timedelta(hours=hour),soc
    def test_night_charge_bridges_morning_before_sun(self):
        c,p,n,s=self.setup_case()
        r=joint.plan(c,p,n,s)
        self.assertGreaterEqual(r['morning_soc'],2/.9/10*100-1e-7)
        self.assertLess(r['morning_soc'],30)
        morning=[w for w in r['windows'] if n+timedelta(hours=6)<=datetime.fromisoformat(w['start'])<n+timedelta(hours=10)]
        self.assertAlmostEqual(sum(w['allocated_kwh'] for w in morning),2,places=5)
        self.assertTrue(r['charges'])
    def test_night_can_discharge_existing_energy_before_pv(self):
        c,p,n,s=self.setup_case(soc=80)
        r=joint.plan(c,p,n,s)
        self.assertEqual(r['planned_kwh'],0)
        self.assertTrue(any(w['action']=='discharge' and w['allocated_kwh']>0 and datetime.fromisoformat(w['start'])<n+timedelta(hours=6) for w in r['windows']))
    def test_energy_is_conserved_at_every_step(self):
        c,p,n,s=self.setup_case(hour=17,soc=45)
        r=joint.plan(c,p,n,s);previous=4.5
        for t in r['trace']:
            self.assertAlmostEqual(t['start_kwh'],previous)
            self.assertGreaterEqual(t['end_kwh'],-1e-8);self.assertLessEqual(t['end_kwh'],8+1e-8)
            a=datetime.fromisoformat(t['start']);b=datetime.fromisoformat(t['end'])
            solar=sum(max(0,(min(b,v['end'])-max(a,v['start'])).total_seconds())/3600*max(0,v['kw']-.5)*.9 for v in c['_pv']['rows'])
            expected=min(8,previous+solar)+t['grid_charge_kwh']-t['discharge_kwh']/.9
            self.assertAlmostEqual(t['end_kwh'],expected,places=6)
            previous=t['end_kwh']
    def test_manual_hold_and_price_ceiling(self):
        c,p,n,s=self.setup_case(soc=80)
        r=joint.plan(c,p,n,s,hold_until=n+timedelta(hours=8))
        self.assertTrue(all(w['allocated_kwh']==0 for w in r['windows'] if datetime.fromisoformat(w['start'])<n+timedelta(hours=8)))
        c['max_buy_ct_kwh']=5
        self.assertEqual(joint.plan(c,p,n,0)['planned_kwh'],0)
    def test_incomplete_forecast_falls_back_without_inventing_sun(self):
        c,p,n,s=self.setup_case();c['_pv']['rows']=c['_pv']['rows'][:8]
        self.assertIsNone(joint.plan(c,p,n,s))
        self.assertNotIn('joint',smart.plan(c,p,n,s))
    def test_ui_and_controller_use_same_plan(self):
        c,p,n,s=self.setup_case()
        preview=smart.plan(c,p,n,s);d=dispatch.plan(c,p,n,s)
        self.assertEqual(d['windows'],preview['joint']['windows'])
        self.assertEqual(dispatch.timeline(c,p,n,s,preview)['windows'],d['windows'])
        self.assertEqual(smart.planned_economics(c,p,preview),preview['joint']['economics'])
    def test_dst_and_device_power_limit(self):
        c,p,n,s=self.setup_case(hour=18,soc=20);c['timezone']='Europe/Berlin'
        r=joint.plan(c,p,n,s,max_power_w=1000)
        self.assertEqual(r['power_w'],1000)
        for w in r['charges']:
            a=datetime.fromisoformat(w['start']);b=datetime.fromisoformat(w['end'])
            self.assertLess(a.astimezone(ZoneInfo(c['timezone'])).hour,6)
            self.assertLessEqual(w['battery_kwh'],((b-a).total_seconds()-130)/3600+1e-8)
            self.assertGreaterEqual((b-a).total_seconds(),190-1e-7)
    def test_selling_to_grid_is_never_planned(self):
        c,p,n,s=self.setup_case(soc=80)
        r=joint.plan(c,p,n,s)
        for t in r['trace']:
            hours=(datetime.fromisoformat(t['end'])-datetime.fromisoformat(t['start'])).total_seconds()/3600
            self.assertLessEqual(t['discharge_kwh'],.5*hours+1e-8)

    def test_evening_consumption_then_next_night_refill(self):
        c,p,n,s=self.setup_case(hour=17,soc=40)
        c.update(extra_load_kwh=2,extra_load_start_hour=18,extra_load_end_hour=20)
        r=joint.plan(c,p,n,s)
        midnight=n.replace(hour=0)+timedelta(days=1)
        evening=sum(w['allocated_kwh'] for w in r['windows'] if datetime.fromisoformat(w['end'])<=midnight)
        self.assertGreater(evening,3.4)
        self.assertGreater(r['planned_kwh'],2)
        self.assertGreaterEqual(r['morning_soc'],2/.9/10*100-1e-7)
        self.assertGreater(r['economics']['saving_ct_kwh'],0)
