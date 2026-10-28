import unittest,tempfile
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from past import summarize,day_bounds,compact_phases,compact_switches
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

    def test_thousands_of_renewed_confirmations_do_not_split_charging(self):
        rows=[]
        for t in range(10,21600,15):
            rows.append((t,'decision',{'battery_power_w':1500,'soc':40,
                'discharge_confirmation':{'locked':True,'time':datetime.fromtimestamp(t+3,timezone.utc).isoformat()}}))
        result=summarize(rows,0,21600,21600)
        self.assertLessEqual(len(result['phases']),6)
        charges=[p for p in result['phases'] if p['action']=='charge' and p['locked']]
        self.assertEqual(len(charges),1)
        self.assertGreater(charges[0]['end']-charges[0]['start'],21500)
        self.assertEqual(len(result['switches']),1)

    def test_real_lock_changes_invalidate_prechange_measurements(self):
        rows=[]
        for t,locked,power in [(10,False,500),(30,True,500),(50,True,500),(70,False,500),(90,False,500)]:
            rows.append((t,'decision',{'battery_power_w':power,'discharge_confirmation':{
                'locked':locked,'time':datetime.fromtimestamp(t+3,timezone.utc).isoformat()}}))
        result=summarize(rows,0,110,110)
        self.assertEqual(next(p for p in result['phases'] if p['start']<=35<p['end'])['action'],'hold')
        self.assertEqual(len(result['switches']),3)
        self.assertTrue(any(p['action']=='charge' and p['locked'] for p in result['phases']))

    def test_compact_summary_preserves_gaps_locks_and_warning(self):
        def rows(middle,locked=False):
            return [dict(start=0,end=600,action='charge',locked=locked),dict(start=600,end=620,action=middle,locked=locked),dict(start=620,end=1200,action='charge',locked=locked)]
        original=rows('idle');summary=compact_phases(original)
        self.assertEqual(len(summary),1);self.assertEqual(summary[0]['brief_count'],1)
        self.assertEqual(summary[0]['brief_seconds'],20);self.assertEqual(len(original),3)
        self.assertEqual(len(compact_phases(rows('unknown'))),3)
        self.assertEqual(len(compact_phases(rows('discharge',True))),3)
        different=rows('hold');different[1]['locked']=True
        self.assertEqual(len(compact_phases(different)),3)
        sustained=rows('idle');sustained[1]['end']=720;sustained[2]['start']=720
        self.assertEqual(len(compact_phases(sustained)),3)

    def test_command_groups_never_hide_stop_restart_or_long_gap(self):
        commands=[dict(time=t,label='Ladebefehl gesendet') for t in (10,112,214)]
        commands += [dict(time=250,label='Stopp bestätigt'),dict(time=280,label='Ladebefehl gesendet'),dict(time=600,label='Ladebefehl gesendet')]
        groups=compact_switches(commands)
        self.assertEqual(len(groups),4);self.assertEqual(groups[0]['count'],3)
        self.assertEqual(groups[0]['end'],214);self.assertEqual(groups[1]['label'],'Stopp bestätigt')
        self.assertEqual(len(commands),6)
