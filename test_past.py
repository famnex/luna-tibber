import unittest,tempfile
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from past import summarize,day_bounds
from audit import Journal

class PastTests(unittest.TestCase):
    def test_command_is_not_measured_charge(self):
        d=summarize([(100,'charge_command',{}),(150,'stopped',{})],0,200,200)
        self.assertTrue(all(p['action']=='unknown' for p in d['phases']))
        self.assertEqual(len(d['switches']),2)
    def test_gaps_and_last_observation_are_not_painted_as_charge(self):
        d=summarize([(10,'snapshot',{'soc':40,'battery_power_w':500}),(70,'snapshot',{'soc':41,'battery_power_w':500}),(600,'snapshot',{'soc':41,'battery_power_w':0})],0,1000,1000)
        self.assertEqual(d['phases'][1]['action'],'charge')
        self.assertEqual(d['phases'][1]['end'],190)
        self.assertEqual(d['phases'][-1]['action'],'unknown')
    def test_future_confirmation_does_not_relabel_precommand_sample(self):
        c={'locked':True,'time':datetime.fromtimestamp(110,timezone.utc).isoformat()}
        d=summarize([(100,'decision',{'battery_power_w':-500,'discharge_confirmation':c}),(120,'decision',{'battery_power_w':0,'discharge_confirmation':c}),(180,'decision',{'battery_power_w':0,'discharge_confirmation':c})],90,200,200)
        self.assertEqual(next(p for p in d['phases'] if p['start']==100)['locked'],False)
        self.assertEqual(next(p for p in d['phases'] if p['start']<=120<p['end'])['action'],'hold')
    def test_repeated_confirmations_are_not_switches(self):
        rows=[(t,'decision',{'battery_power_w':0,'discharge_confirmation':{'locked':True,'time':datetime.fromtimestamp(t,timezone.utc).isoformat()}}) for t in (10,20,30,40)]
        self.assertEqual(len(summarize(rows,0,100,100)['switches']),1)
    def test_simulation_and_invalid_values_ignored(self):
        d=summarize([(100,'decision',{'live':False,'battery_power_w':1000,'soc':50}),(150,'snapshot',{'battery_power_w':float('nan')})],0,200,200)
        self.assertEqual(d['soc'],[])
        self.assertTrue(all(p['action']=='unknown' for p in d['phases']))
    def test_dst_and_retention(self):
        now=datetime(2026,10,27,tzinfo=timezone.utc).timestamp()
        a,b=day_bounds('2026-10-25','Europe/Berlin',now)
        self.assertEqual(b-a,25*3600)
        with self.assertRaises(ValueError):day_bounds('2026-10-28','Europe/Berlin',now)
        with self.assertRaises(ValueError):day_bounds('2026-10-19','Europe/Berlin',now)
    def test_readonly_archive_prices_cache_and_no_current_plan(self):
        now=datetime(2026,10,27,12,tzinfo=timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as folder,patch('audit.time.time',return_value=now):
            j=Journal(Path(folder));stamp=datetime(2026,10,26,12,tzinfo=timezone.utc).isoformat()
            j.record({'timezone':'Europe/Berlin'},{'time':stamp,'event':'decision','soc':40,'battery_power_w':500,'diagnostic_plan':{'windows':[{'action':'hold'}]}},prices=[{'start':'2026-10-26T12:00:00+00:00','end':'2026-10-26T12:15:00+00:00','ct':20}])
            a=j.timeline('2026-10-26');self.assertEqual(a['prices'][0]['ct'],20);self.assertEqual(a['samples'],1)
            self.assertIs(j.timeline('2026-10-26'),a)
            self.assertFalse(any(p['action']=='hold' for p in a['phases']))
