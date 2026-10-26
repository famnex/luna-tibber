import unittest,tempfile
from pathlib import Path
from datetime import datetime,timezone
from diagnosis import summarize,plan_change,sample_context
from audit import Journal

class DiagnosisTests(unittest.TestCase):
    def sample(self,house=500,pv=0,evening=False):
        return {'meter':{'valid':True,'house_w':house,'pv_dc_w':pv},'measurement_context':{'load_w':500,'pv_forecast_w':0,'evening':evening}}
    def test_same_period_and_gap_exclusion(self):
        r=summarize([(0,self.sample()),(300,self.sample(1500)),(1200,self.sample())],1)
        t=r['totals']['house'];self.assertAlmostEqual(t['hours'],1/12)
        self.assertAlmostEqual(t['actual_kwh'],1/12);self.assertAlmostEqual(t['planned_kwh'],1/24)
    def test_invalid_breaks_pair(self):
        r=summarize([(0,self.sample()),(100,{'meter':{'valid':False}}),(300,self.sample())],1)
        self.assertEqual(r['totals']['house']['hours'],0);self.assertEqual(r['invalid_samples'],1)
    def test_evening_boundary_not_mixed(self):
        r=summarize([(0,self.sample()),(300,self.sample(evening=True)),(600,self.sample(evening=True))],1)
        self.assertAlmostEqual(r['totals']['evening']['hours'],1/12)
    def test_hold_drop_separate_from_reported_power(self):
        def row(soc,locked=True):return {'soc':soc,'battery_power_w':0,'discharge_confirmation':{'locked':locked}}
        r=summarize([(0,row(26)),(60,row(25)),(120,row(24,False)),(180,row(24)),(240,row(23))],1)
        self.assertEqual([v['soc_drop'] for v in r['hold_spans']],[1,1])
        self.assertEqual(r['hold_spans'][0]['reported_discharge_kwh'],0)
    def test_new_confirmation_not_false_external_change(self):
        d=self.sample();d['meter'].update(discharge_limit_w=5000,measured_at='2026-10-26T01:00:00+00:00')
        d['discharge_confirmation']={'locked':True,'time':'2026-10-26T01:00:05+00:00'}
        self.assertFalse(summarize([(0,d)],1)['limit_mismatches'])
        d['discharge_confirmation']['time']='2026-10-26T00:59:00+00:00'
        self.assertEqual(len(summarize([(0,d)],1)['limit_mismatches']),1)
    def test_reason_names_pv_and_morning(self):
        a={'config':{},'prices_hash':'x','soc':32,'joint':{'night_end':'same','planned_kwh':.34,'solar':{'generation_kwh':8.93},'guard':{'hold':True}}}
        b={**a,'joint':{'night_end':'same','planned_kwh':0,'solar':{'generation_kwh':10.69},'guard':{'hold':False},'morning_soc':18,'bridge':{'required_soc':16.05}}}
        text=plan_change(a,b);self.assertIn('8,93 → 10,69',text);self.assertIn('0,34 → 0,00',text);self.assertIn('16,05',text)
    def test_missing_forecast_not_zero(self):
        c={'timezone':'Europe/Berlin','base_load_w':500,'extra_load_kwh':2,'extra_load_start_hour':17,'extra_load_end_hour':19}
        r=sample_context(c,{},datetime(2026,10,26,17,tzinfo=timezone.utc).timestamp())
        self.assertIsNone(r['pv_forecast_w']);self.assertEqual(r['load_w'],1500)
    def test_journal_persists_measurements(self):
        with tempfile.TemporaryDirectory() as path:
            j=Journal(Path(path));j.record({'base_load_w':500,'timezone':'Europe/Berlin'},{'event':'snapshot',**self.sample()})
            e=j.entries(all_checks=True)['events'][0]['data'];self.assertIn('meter',e);self.assertEqual(e['measurement_context']['load_w'],500)
