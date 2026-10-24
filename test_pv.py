import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch
import luna
import pv
import smart
import dispatch

class PvTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.now=datetime(2026,10,24,tzinfo=timezone.utc)
        self.c={**luna.DEFAULT,'timezone':'UTC','pv_enabled':True,'pv_kwp':8,
                'pv_latitude':51.2,'pv_longitude':10.0,'pv_factor':.7,
                'battery_capacity_kwh':10,'base_load_w':500,'charge_power_w':5000,
                'smart_discharge_enabled':True,'roundtrip_efficiency':1}
        self.rows=[{'start':self.now+timedelta(hours=i),'end':self.now+timedelta(hours=i+1),
                    'kw':3 if 10<=i%24<14 else 0} for i in range(72)]
        self.prices=[{'start':self.now+timedelta(minutes=15*i),'end':self.now+timedelta(minutes=15*(i+1)),
                      'ct':10 if i%96<24 else 40} for i in range(192)]
    def tearDown(self):self.tmp.cleanup()
    def attached(self):
        pv.refresh(self.c,self.folder,self.now,lambda c:self.rows)
        return pv.attach(self.c,self.folder,self.now)
    def test_parser_preceding_hour_losses_and_clipping(self):
        data={'hourly':{'time':[self.now.timestamp()+3600,self.now.timestamp()+7200],
                        'global_tilted_irradiance':[1000,None]}}
        rows=pv.parse(self.c,data)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['start'],self.now)
        self.assertAlmostEqual(rows[0]['kw'],5*.7)
        data['hourly']['global_tilted_irradiance'][0]=float('nan')
        with self.assertRaises(ValueError):pv.parse(self.c,data)
    def test_disabled_never_fetches(self):
        fetch=Mock();pv.refresh({**self.c,'pv_enabled':False},self.folder,self.now,fetch)
        fetch.assert_not_called();self.assertFalse(pv.read({**self.c,'pv_enabled':False},self.folder)['rows'])
    def test_cache_refresh_expiry_retry_and_config_identity(self):
        fetch=Mock(return_value=self.rows)
        pv.refresh(self.c,self.folder,self.now,fetch)
        pv.refresh(self.c,self.folder,self.now+timedelta(hours=2),fetch);self.assertEqual(fetch.call_count,1)
        fetch.side_effect=OSError('offline')
        later=self.now+timedelta(hours=3)
        pv.refresh(self.c,self.folder,later,fetch);self.assertEqual(fetch.call_count,2)
        pv.refresh(self.c,self.folder,later+timedelta(minutes=1),fetch);self.assertEqual(fetch.call_count,2)
        self.assertTrue(pv.read(self.c,self.folder,later)['rows'])
        self.assertFalse(pv.read(self.c,self.folder,self.now+timedelta(hours=7))['rows'])
        changed={**self.c,'pv_kwp':4}
        self.assertFalse(pv.read(changed,self.folder,later)['rows'])
        pv.refresh(changed,self.folder,later,fetch);self.assertEqual(fetch.call_count,3)
        self.assertFalse(pv.read(changed,self.folder,later)['rows'])
    def test_missing_hour_rejected_and_throttled(self):
        fetch=Mock(return_value=self.rows[:15]+self.rows[16:])
        pv.refresh(self.c,self.folder,self.now,fetch)
        self.assertFalse(pv.read(self.c,self.folder,self.now)['rows'])
        pv.refresh(self.c,self.folder,self.now+timedelta(minutes=1),fetch)
        self.assertEqual(fetch.call_count,1)
    def test_corrupt_cache_and_future_timestamp(self):
        self.attached();path=self.folder/'pv-forecast.json';data=json.loads(path.read_text())
        data['fetched_at']=self.now.timestamp()+3600;path.write_text(json.dumps(data))
        self.assertFalse(pv.read(self.c,self.folder,self.now)['rows'])
        path.write_text('not-json');self.assertFalse(pv.read(self.c,self.folder,self.now)['rows'])
    def test_surplus_reduces_target_but_morning_energy_is_preserved(self):
        c=self.attached();p=smart.plan(c,self.prices,self.now,0)
        # 06-10 needs 2kWh before solar; 10-14 delivers 10kWh surplus;
        # 14-24 needs 5kWh. Target may drop from 8kWh to 2kWh, never zero.
        self.assertAlmostEqual(p['effective_target_soc'],20)
        self.assertAlmostEqual(p['needed_kwh'],2)
        self.assertAlmostEqual(p['pv']['generation_kwh'],12)
        self.assertAlmostEqual(p['pv']['direct_kwh'],2)
        self.assertAlmostEqual(p['pv']['reduction_kwh'],6)
        self.assertTrue(p['windows']);self.assertTrue(p['complete'])
        state={'soc':21,'battery_status':2,'ac_charge_enabled':True,'max_charge_power_w':5000}
        self.assertFalse(luna.decide(c,state,self.prices,self.now)[0])
        self.assertTrue(luna.decide({**c,'_manual':True},state,self.prices,self.now)[0])
    def test_morning_extra_load_and_charging_losses(self):
        c={**self.attached(),'extra_load_kwh':2,'extra_load_start_hour':7,'extra_load_end_hour':9,'roundtrip_efficiency':.81}
        p=pv.night_target(c,self.now+timedelta(hours=6),5000)
        self.assertAlmostEqual(p['target_soc'],4/.9/10*100)
    def test_evening_load_keeps_full_target_if_surplus_not_sufficient(self):
        c={**self.attached(),'extra_load_kwh':5,'extra_load_start_hour':18,'extra_load_end_hour':20}
        p=pv.night_target(c,self.now+timedelta(hours=6),5000)
        self.assertEqual(p['target_soc'],80)
    def test_no_surplus_no_reduction_and_no_phantom_solar_energy(self):
        self.rows=[{**r,'kw':.3 if r['kw'] else 0} for r in self.rows]
        c=self.attached();p=pv.night_target(c,self.now+timedelta(hours=6),5000)
        self.assertEqual(p['surplus_kwh'],0);self.assertEqual(p['target_soc'],80)
        d=dispatch.plan(c,self.prices,self.now+timedelta(hours=6),10)
        self.assertLessEqual(sum(w.get('allocated_kwh',0) for w in d['windows']),1+1e-8)
    def test_storage_charge_power_limit_caps_credit(self):
        c=self.attached();p=pv.night_target(c,self.now+timedelta(hours=6),200)
        self.assertAlmostEqual(p['surplus_kwh'],.8)
        self.assertAlmostEqual(p['target_soc'],72)
    def test_missing_or_stale_data_uses_original_target(self):
        for c in (self.c,pv.attach(self.attached(),self.folder,self.now+timedelta(hours=7))):
            p=smart.plan(c,self.prices,self.now,0)
            self.assertEqual(p['needed_kwh'],8);self.assertFalse(p['pv']['applied'])
    def test_direct_pv_not_allocated_as_battery_discharge(self):
        c=self.attached();start=self.now+timedelta(hours=10)
        d=dispatch.demand_rows(c,self.prices,start,start+timedelta(hours=1))
        self.assertTrue(all(r['load_kw']==0 for r in d))
        p=dispatch.plan(c,self.prices,start,40)
        self.assertTrue(p['complete']) # Includes zero-load solar slots without division by zero.
        self.assertTrue(all(w.get('allocated_kwh',0)==0 for w in p['windows'] if datetime.fromisoformat(w['start'])<self.now+timedelta(hours=14)))
    def test_daylight_saving_time_uses_utc_intervals(self):
        c={**self.attached(),'timezone':'Europe/Berlin'}
        start=datetime(2026,10,25,5,tzinfo=timezone.utc)
        p=pv.night_target(c,start,5000)
        self.assertTrue(p['applied']);self.assertAlmostEqual(p['generation_kwh'],12)
    def test_invalid_settings(self):
        for change in ({'pv_kwp':0},{'pv_factor':1.1},{'pv_latitude':91},{'pv_tilt':-1},{'pv_enabled':'yes'},{'base_load_w':0}):
            with self.assertRaises(ValueError):luna.validate({**self.c,**change})
    def test_snapshot_reads_cache_without_network(self):
        import web
        self.attached();luna.write_json(self.folder/'config.json',self.c)
        app=web.Dashboard(self.folder,start_worker=False)
        with patch('pv.fetch',side_effect=AssertionError('No HTTP in snapshot')):
            status=app.snapshot()
        self.assertTrue(status['pv_forecast']['enabled'])
        self.assertNotIn('_pv',status['settings']);self.assertNotIn('rows',status['pv_forecast'])
