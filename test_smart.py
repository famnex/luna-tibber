import unittest
from datetime import datetime,timedelta,timezone
import luna
from smart import plan

class SmartTests(unittest.TestCase):
    def setUp(self):
        self.c={**luna.DEFAULT,'battery_idle_w':0,'timezone':'UTC','battery_capacity_kwh':10,
                'target_soc':80,'charge_power_w':2000,'night_start_hour':0,'night_end_hour':6,
                'use_start_hour':6,'use_end_hour':9,'max_buy_ct_kwh':20}
        self.now=datetime(2026,10,24,tzinfo=timezone.utc)
        self.rows=[{'start':self.now+timedelta(minutes=15*i),
                    'end':self.now+timedelta(minutes=15*(i+1)),
                    'ct':10 if i in (4,12) else 18 if i<24 else 40} for i in range(36)]
    def test_energy_duration_and_cheapest_separated_slots(self):
        p=plan(self.c,self.rows,self.now,73)
        self.assertAlmostEqual(p['needed_kwh'],.7)
        self.assertAlmostEqual(p['duration_minutes'],21)
        self.assertTrue(p['complete'])
        self.assertEqual([w['start'] for w in p['windows']], [self.rows[i]['start'].isoformat() for i in (4,12)])
    def test_pause_resume_decisions(self):
        state={'soc':73,'battery_status':2,'ac_charge_enabled':True,'max_charge_power_w':2000}
        self.assertFalse(luna.decide(self.c,state,self.rows,self.now)[0])
        self.assertTrue(luna.decide(self.c,state,self.rows,self.rows[4]['start'])[0])
        state['soc']=77
        self.assertFalse(luna.decide(self.c,state,self.rows,self.rows[8]['start'])[0])
        self.assertTrue(luna.decide(self.c,state,self.rows,self.rows[12]['start'])[0])
        state['soc']=80
        self.assertFalse(luna.decide(self.c,state,self.rows,self.rows[12]['start'])[0])
    def test_missing_price_and_capacity(self):
        self.assertFalse(plan(self.c,self.rows[:10],self.now,30)['windows'])
        self.assertFalse(plan({**self.c,'battery_capacity_kwh':0},self.rows,self.now,30)['windows'])
    def test_unreachable_and_device_power_limit(self):
        p=plan(self.c,self.rows,self.now,5,500)
        self.assertEqual(p['power_w'],500)
        self.assertFalse(p['complete'])
        self.assertLess(p['planned_kwh'],p['needed_kwh'])
    def test_price_cap_and_target_reached(self):
        self.assertFalse(plan({**self.c,'max_buy_ct_kwh':5},self.rows,self.now,30)['windows'])
        p=plan(self.c,self.rows,self.now,80)
        self.assertEqual(p['needed_kwh'],0)
        self.assertFalse(p['windows'])
    def test_negative_prices_selected_first(self):
        self.rows[16]['ct']=-5
        p=plan(self.c,self.rows,self.now,79)
        self.assertEqual(p['windows'][0]['start'],self.rows[16]['start'].isoformat())
    def test_no_charge_without_a_known_consumption_comparison(self):
        p=plan(self.c,self.rows,self.now+timedelta(hours=7),73)
        self.assertFalse(p['windows'])
    def test_dst_night_uses_real_elapsed_hours(self):
        c={**self.c,'timezone':'Europe/Berlin'}
        now=datetime(2026,10,24,22,tzinfo=timezone.utc)
        rows=[{'start':now+timedelta(minutes=15*i),'end':now+timedelta(minutes=15*(i+1)),'ct':10 if i<28 else 40} for i in range(40)]
        p=plan(c,rows,now,30)
        self.assertTrue(p['complete'])
        self.assertEqual(datetime.fromisoformat(p['night_end'])-now,timedelta(hours=7))

    def test_ui_economics_uses_selected_purchase_prices(self):
        from smart import planned_economics
        from unittest.mock import patch
        a=self.now+timedelta(hours=1);b=self.now+timedelta(hours=2)
        preview={'complete':True,'windows':[{'start':a.isoformat(),'battery_kwh':1},{'start':b.isoformat(),'battery_kwh':3}]}
        def economics(c,prices,now):
            effective=10 if now==a else 20
            return dict(effective_ct_kwh=effective,reference_ct_kwh=30,saving_ct_kwh=30-effective,
                        window_start=(self.now+timedelta(hours=6)).isoformat(),window_end=(self.now+timedelta(hours=9)).isoformat())
        with patch('luna.economics_plan',side_effect=economics):
            result=planned_economics(self.c,[],preview)
        self.assertAlmostEqual(result['effective_ct_kwh'],17.5)
        self.assertAlmostEqual(result['saving_ct_kwh'],12.5)
        self.assertTrue(result['ok'])
        self.assertNotIn('saving_ct_kwh',planned_economics(self.c,[],{'windows':[],'reason':'PV deckt Restbedarf'}))
