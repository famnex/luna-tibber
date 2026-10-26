import math
import unittest
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import luna,smart,dispatch,joint

class JointTests(unittest.TestCase):
    def setup_case(self, hour=0, soc=0):
        a=datetime(2026,10,24,tzinfo=timezone.utc)
        c={**luna.DEFAULT,'battery_idle_w':0,'battery_floor_soc':0,'timezone':'UTC','pv_enabled':True,'smart_discharge_enabled':True,
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
        r=joint.plan(c,p,n,s)
        self.assertFalse(r['pv_available'])
        self.assertGreater(r['bridge']['required_kwh'],8)
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


    def test_reserve_is_independent_of_soc_drop_from_unexpected_load(self):
        c,p,n,s=self.setup_case(hour=2,soc=70)
        full=joint.plan(c,p,n,70);low=joint.plan(c,p,n,30)
        self.assertAlmostEqual(full['guard']['required_kwh'],low['guard']['required_kwh'])
        self.assertFalse(full['guard']['hold']);self.assertTrue(low['guard']['hold'])
        self.assertEqual(low['windows'][0]['action'],'hold')
        self.assertEqual(dispatch.plan(c,p,n,30)['hold'],True)

    def test_hysteresis_prevents_repeated_switching(self):
        c,p,n,s=self.setup_case(hour=2,soc=70)
        g=joint.plan(c,p,n,s)['guard']
        middle=(g['threshold_soc']+g['release_soc'])/2
        self.assertFalse(joint.plan(c,p,n,middle)['guard']['hold'])
        self.assertTrue(joint.plan({**c,'_guard_held':True},p,n,middle)['guard']['hold'])
        self.assertFalse(joint.plan({**c,'_guard_held':True},p,n,g['release_soc']+1)['guard']['hold'])

    def test_cloudy_day_requires_more_retained_energy(self):
        c,p,n,s=self.setup_case(hour=2,soc=70)
        sunny=joint.plan(c,p,n,s)
        c['_pv']['rows']=[{**r,'kw':0} for r in c['_pv']['rows']]
        cloudy=joint.plan(c,p,n,s)
        self.assertGreater(cloudy['guard']['required_kwh'],sunny['guard']['required_kwh'])
        self.assertGreater(cloudy['bridge']['required_kwh'],sunny['bridge']['required_kwh'])

    def test_reserve_is_released_when_future_demand_has_passed(self):
        c,p,n,s=self.setup_case(hour=23,soc=70)
        p=[r for r in p if r['start'].date()==n.date()]
        # At the last expensive interval the next cheap recharge is ahead;
        # direct helper verifies no permanent SOC reserve at horizon end.
        from protection import reserve
        g=reserve([0.]*81,8,40,.9,0,10,1)
        self.assertEqual(g['required_kwh'],0);self.assertFalse(g['hold'])

    def test_old_car_schedule_and_manual_buffer_are_migrated_away(self):
        c,p,n,s=self.setup_case();c['pv_enabled']=False
        c=luna.validate({**c,'ev_protection_enabled':True,'ev_start_hour':22,'ev_end_hour':7,'morning_buffer_kwh':9})
        for key in ('ev_protection_enabled','ev_start_hour','ev_end_hour','morning_buffer_kwh'):
            self.assertNotIn(key,c)
        c['pv_enabled']=True
        r=joint.plan(c,p,n,s)
        self.assertAlmostEqual(r['bridge']['buffer_kwh'],r['bridge']['demand_kwh']*.1)

    def test_missing_prices_hold_but_no_sun_uses_conservative_model(self):
        c,p,n,s=self.setup_case(hour=2,soc=70)
        d=dispatch.plan(c,[],n,s)
        self.assertTrue(d['hold']);self.assertTrue(d['guard']['unavailable'])
        c['_pv']['rows']=[]
        r=joint.plan(c,p,n,s)
        self.assertFalse(r['pv_available']);self.assertGreater(r['guard']['required_kwh'],0)

    def test_device_floor_and_unreachable_minimum(self):
        c,p,n,s=self.setup_case()
        c.update(battery_floor_soc=5,max_buy_ct_kwh=0)
        r=joint.plan(c,p,n,s)
        self.assertEqual(r['planned_kwh'],0)
        self.assertGreater(r['bridge']['shortfall_kwh'],2)
        self.assertGreater(r['bridge']['required_soc'],25)
        for change in ({'battery_floor_soc':float('nan')},{'battery_floor_soc':20,'target_soc':20}):
            with self.assertRaises(ValueError):luna.validate({**c,'pv_enabled':False,**change})

    def test_morning_day_plan_survives_unpublished_next_night_prices(self):
        c,p,n,s=self.setup_case(hour=6,soc=40)
        p=[r for r in p if r['end']<=n.replace(hour=0)+timedelta(days=1)]
        r=joint.plan(c,p,n,s)
        self.assertIsNotNone(r);self.assertFalse(r['night_complete'])
        self.assertIsNone(r['morning_soc'])
        self.assertFalse(r['guard']['hold'])
        self.assertEqual(r['windows'][0]['action'],'discharge')
        self.assertTrue(dispatch.plan(c,p,n,s)['complete'])

    def test_no_permanent_reserve_for_zero_price_or_no_remaining_demand(self):
        from protection import reserve
        for price in (0,20):
            g=reserve([0.]*81,8,price,.9,0,10,1)
            self.assertEqual(g['required_kwh'],0)

class IntervalRegressionTests(JointTests):
    def test_discharge_does_not_split_tariff_rows_at_energy_knots(self):
        c,p,n,s=self.setup_case(hour=17,soc=43)
        r=joint.plan(c,p,n,s)
        for w,t in zip(r['windows'],r['trace']):
            self.assertEqual(w['start'],t['start'])
            self.assertEqual(w['end'],t['end'])
        self.assertEqual(len(r['windows']),len(r['trace']))
        for t in r['trace']:
            if t['discharge_kwh']>1e-7 and t['end_kwh']>1e-7:
                hours=(datetime.fromisoformat(t['end'])-datetime.fromisoformat(t['start'])).total_seconds()/3600
                self.assertAlmostEqual(t['discharge_kwh'],.5*hours)

    def test_phase_charge_duration_matches_energy_not_tariff_length(self):
        c,p,n,s=self.setup_case()
        r=joint.plan(c,p,n,s)
        phases=[w for w in r['phases'] if w['action']=='charge']
        self.assertTrue(phases)
        for w in phases:
            hours=(datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])).total_seconds()/3600
            self.assertAlmostEqual(hours*5,w['kwh'],places=6)
        self.assertAlmostEqual(sum(w['kwh'] for w in phases),r['planned_kwh'])

class ContinuousChargeTests(unittest.TestCase):
    def test_command_crosses_selected_boundary_but_not_price_ceiling(self):
        from unittest.mock import patch
        c={**luna.DEFAULT,'max_buy_ct_kwh':20}
        a=datetime(2026,10,26,2,45,tzinfo=timezone.utc)
        b=a+timedelta(minutes=15)
        prices=[dict(start=a,end=b,ct=14.09),dict(start=b,end=b+timedelta(minutes=15),ct=14.19)]
        windows=[dict(start=a.isoformat(),end=(b+timedelta(seconds=130)).isoformat()),dict(start=b.isoformat(),end=(b+timedelta(minutes=9)).isoformat())]
        snapshot=dict(soc=30,battery_status=2,ac_charge_enabled=True)
        with patch('smart.plan',return_value=dict(windows=windows,reason='test')):
            ok,_,slot=luna.decide(c,snapshot,prices,b-timedelta(seconds=60))
            self.assertTrue(ok)
            self.assertGreater(slot['end'],b)
            prices[1]['ct']=100
            self.assertFalse(luna.decide(c,snapshot,prices,b-timedelta(seconds=60))[0])

    def test_planner_uses_full_intermediate_tariff_interval(self):
        c,p,n,s=JointTests().setup_case()
        r=joint.plan(c,p,n,s)
        self.assertTrue(any(abs(w['battery_kwh']-1.25)<1e-7 for w in r['charges']))
        for w in r['phases']:
            self.assertLess(w['start'],w['end'])

    def test_idle_consumes_energy_during_manual_hold(self):
        c,p,n,s=JointTests().setup_case(soc=80);c['battery_idle_w']=100;c['max_buy_ct_kwh']=0
        r=joint.plan(c,p,n,s,hold_until=n+timedelta(hours=6))
        six=[t for t in r['trace'] if datetime.fromisoformat(t['end'])<=n+timedelta(hours=6)]
        self.assertAlmostEqual(six[-1]['end_kwh'],7.4,places=6)
        self.assertTrue(all(t['discharge_kwh']==0 for t in six))
        self.assertAlmostEqual(sum(t['idle_kwh'] for t in six),.6)

    def test_idle_adds_morning_bridge_and_more_charge(self):
        c,p,n,s=JointTests().setup_case(soc=0);base=joint.plan(c,p,n,s)
        c['battery_idle_w']=100;r=joint.plan(c,p,n,s)
        self.assertAlmostEqual(r['bridge']['idle_kwh'],.4)
        self.assertGreater(r['bridge']['required_kwh'],base['bridge']['required_kwh'])
        self.assertGreater(r['planned_kwh'],base['planned_kwh'])
        self.assertGreaterEqual(r['morning_soc']+1e-6,r['bridge']['required_soc'])

    def test_idle_energy_balance_including_empty_and_charge(self):
        c,p,n,s=JointTests().setup_case(soc=0);c['battery_idle_w']=100
        r=joint.plan(c,p,n,s)
        for t in r['trace']:
            a=datetime.fromisoformat(t['start']);b=datetime.fromisoformat(t['end'])
            solar=sum(max(0,(min(b,v['end'])-max(a,v['start'])).total_seconds())/3600*max(0,v['kw']-.5)*.9 for v in c['_pv']['rows'])
            expected=max(0,min(8,t['start_kwh']+solar-t['idle_kwh'])+t['grid_charge_kwh']-t['discharge_kwh']/.9)
            self.assertAlmostEqual(t['end_kwh'],expected,places=6)
