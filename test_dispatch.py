import unittest
from datetime import datetime,timedelta,timezone
import luna
from dispatch import plan,timeline,demand_rows

class LegacyDispatchTests(unittest.TestCase):
    """The retained allocator still supplies the comparison-only economics model."""
    def setUp(self):
        self.c={**luna.DEFAULT,'_legacy_dispatch':True,'battery_idle_w':0,'smart_discharge_enabled':True,'battery_capacity_kwh':10,'base_load_w':500,'reserve_soc':20,'roundtrip_efficiency':1,'min_saving_ct_kwh':2}
        self.now=datetime(2026,10,24,10,tzinfo=timezone.utc) # noon local, 12 h until next night
        self.prices=[{'start':self.now+timedelta(hours=i),'end':self.now+timedelta(hours=i+1),'ct':50 if i in (6,7) else 20} for i in range(12)]
    def test_reserves_for_evening_and_releases_then(self):
        p=plan(self.c,self.prices,self.now,10) # 1 kWh, two expensive hours
        self.assertTrue(p['hold'])
        releases=[w for w in p['windows'] if w['action']=='discharge' and not w.get('surplus_only')]
        self.assertEqual([w['ct'] for w in releases],[50,50])
        self.assertFalse(plan(self.c,self.prices,self.now+timedelta(hours=6),30)['hold'])
    def test_more_energy_and_dynamic_soc(self):
        self.assertFalse(plan(self.c,self.prices,self.now,90)['hold'])
        self.assertTrue(plan(self.c,self.prices,self.now,10)['hold'])
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
        p=plan(self.c,self.prices,self.now,7)
        kwh=sum(w.get('allocated_kwh',0) for w in p['windows'])
        self.assertAlmostEqual(kwh,.7)
        self.assertTrue(any(w.get('surplus_only') for w in p['windows']))
    def test_charge_economics_uses_evening_slots(self):
        c={**self.c,'timezone':'UTC','target_soc':10}
        now=datetime(2026,10,24,tzinfo=timezone.utc)
        rows=[{'start':now+timedelta(hours=i),'end':now+timedelta(hours=i+1),'ct':15 if i<6 else 50 if i in (18,19) else 10} for i in range(24)]
        p=luna.economics_plan(c,rows,now)
        self.assertTrue(p['ok']);self.assertEqual(p['reference_ct_kwh'],50)

    def test_reserve_breakdown(self):
        p=plan({**self.c,'roundtrip_efficiency':.85},self.prices,self.now,48)
        self.assertAlmostEqual(p['stored_kwh'],4.8)
        self.assertAlmostEqual(p['available_kwh'],4.4253813395)
        self.assertNotIn('reserve_kwh',p)

    def test_surplus_after_peak_even_below_legacy_reserve(self):
        p=plan(self.c,self.prices,self.now,30)
        tail=[w for w in p['windows'] if w.get('surplus_only')]
        self.assertTrue(tail)
        self.assertTrue(all(w['action']=='discharge' and w['allocated_kwh']==0 for w in tail))
        later=self.now+timedelta(hours=10)
        self.assertFalse(plan(self.c,self.prices,later,25)['hold'])
        p=plan(self.c,self.prices,later,20)
        self.assertFalse(p['hold']);self.assertTrue(all(w['action']=='discharge' for w in p['windows']))

    def test_extra_demand_is_energy_not_minimum_soc(self):
        c={**self.c,'extra_load_kwh':2,'extra_load_start_hour':18,'extra_load_end_hour':20}
        rows=demand_rows(c,self.prices,self.now,self.now+timedelta(hours=12))
        total=sum((w['end']-w['start']).total_seconds()/3600*w['load_kw'] for w in rows)
        self.assertAlmostEqual(total,8) # 6 kWh base + 2 kWh cooking
        p=plan(c,self.prices,self.now,30)
        self.assertAlmostEqual(sum(w.get('allocated_kwh',0) for w in p['windows']),3)
        self.assertTrue(all(w['ct']==50 for w in p['windows'] if w.get('allocated_kwh',0)>0))
        self.assertEqual(p['stored_kwh'],3)

    def test_demand_edges_and_dst(self):
        c={**self.c,'extra_load_kwh':2,'extra_load_start_hour':2,'extra_load_end_hour':3}
        a=datetime(2026,10,25,0,tzinfo=timezone.utc);b=a+timedelta(hours=2)
        rows=demand_rows(c,[{'start':a,'end':b,'ct':20}],a,b)
        self.assertAlmostEqual(sum((r['end']-r['start']).total_seconds()/3600*r['load_kw'] for r in rows),3)
        a=datetime(2026,3,29,0,tzinfo=timezone.utc);b=a+timedelta(hours=2)
        rows=demand_rows(c,[{'start':a,'end':b,'ct':20}],a,b)
        self.assertAlmostEqual(sum((r['end']-r['start']).total_seconds()/3600*r['load_kw'] for r in rows),1)

    def test_rolling_forecast_includes_known_dst_day(self):
        from smart import plan as charge_plan
        from zoneinfo import ZoneInfo
        c={**self.c,'_legacy_dispatch':False,'roundtrip_efficiency':.85,'charge_power_w':5000}
        a=datetime(2026,10,23,22,tzinfo=timezone.utc)
        rows=[]
        for i in range(196):
            start=a+timedelta(minutes=15*i);hour=start.astimezone(ZoneInfo(c['timezone'])).hour
            rows.append({'start':start,'end':start+timedelta(minutes=15),'ct':10 if hour<6 else 40 if 18<=hour<20 else 25})
        charge=charge_plan(c,rows,self.now,48)
        self.assertTrue(charge['projected']);self.assertGreaterEqual(charge['planning_soc'],c['battery_floor_soc'])
        self.assertGreater(charge['needed_kwh'],0)
        self.assertEqual(datetime.fromisoformat(charge['joint']['plan_end']),rows[-1]['end'])
        p=timeline(c,rows,self.now,48,charge)
        self.assertTrue(p['future_complete']);self.assertGreaterEqual(p['future_soc'],c['battery_floor_soc']);self.assertLessEqual(p['future_soc'],c['target_soc'])
        tomorrow=datetime(2026,10,25,5,tzinfo=timezone.utc)
        self.assertTrue(any(datetime.fromisoformat(w['start'])>=tomorrow and w['action']=='discharge' for w in p['windows']))
        elapsed=sum((datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])).total_seconds() for w in p['windows'])
        self.assertEqual(elapsed,(rows[-1]['end']-self.now).total_seconds())

    def test_missing_tomorrow_never_invents_forecast(self):
        p=timeline(self.c,self.prices,self.now,48,{'planned_kwh':0})
        self.assertFalse(p['future_complete'])
        self.assertFalse(any(w['action']=='discharge' and w.get('projected') for w in p['windows']))

    def test_forecast_respects_manual_hold(self):
        from dispatch import projected_soc
        end=self.now+timedelta(hours=12)
        soc,complete=projected_soc(self.c,self.prices,self.now,48,end,end)
        self.assertTrue(complete);self.assertEqual(soc,48)

    def test_extra_settings_validation(self):
        for changes in ({'extra_load_kwh':-1},{'extra_load_kwh':float('nan')},
                        {'extra_load_start_hour':19,'extra_load_end_hour':17},
                        {'extra_load_start_hour':17.5}):
            with self.assertRaises(ValueError):luna.validate({**self.c,**changes})
        self.assertEqual(luna.validate({**self.c,'extra_load_kwh':2})['extra_load_kwh'],2)

    def test_reference_price_weights_demand_not_permission_duration(self):
        c={**self.c,'timezone':'UTC','target_soc':80,'extra_load_kwh':2,
           'extra_load_start_hour':18,'extra_load_end_hour':20}
        now=datetime(2026,10,24,tzinfo=timezone.utc)
        rows=[{'start':now+timedelta(hours=i),'end':now+timedelta(hours=i+1),
               'ct':10 if i<6 else 50 if i in (18,19) else 20} for i in range(24)]
        p=luna.economics_plan(c,rows,now)
        # 3 kWh at 50ct (cooking + base), 5 kWh at 20ct. Surplus permission adds 0.
        self.assertAlmostEqual(p['reference_ct_kwh'],31.25)

    def test_peak_demand_is_kept_and_surplus_used_earlier(self):
        c={**self.c,'extra_load_kwh':2,'extra_load_start_hour':18,'extra_load_end_hour':20}
        p=plan(c,self.prices,self.now,50)
        peak=sum(w.get('allocated_kwh',0) for w in p['windows'] if w.get('ct')==50)
        earlier=sum(w.get('allocated_kwh',0) for w in p['windows'] if datetime.fromisoformat(w['end'])<=self.now+timedelta(hours=6))
        self.assertAlmostEqual(peak,3) # 2 kWh cooking + 1 kWh base load
        self.assertAlmostEqual(earlier,2)
        self.assertFalse(p['hold'])
        self.assertAlmostEqual(sum(w.get('allocated_kwh',0) for w in p['windows']),5)
        self.assertGreaterEqual(p['reserved_later_kwh'],3)

    def test_legacy_reserve_is_ignored_on_upgrade(self):
        c=luna.validate({**self.c,'reserve_soc':90})
        self.assertEqual(c['reserve_soc'],0)
        p=plan(c,self.prices,self.now,10)
        self.assertAlmostEqual(p['available_kwh'],1)
        self.assertFalse(plan(c,self.prices,self.now+timedelta(hours=6),10)['hold'])
        self.assertFalse(plan(c,self.prices,self.now,0)['hold'])
