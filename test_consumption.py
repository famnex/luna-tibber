import json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
import consumption,manual,dispatch,luna

class ConsumptionTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,10,30,8,tzinfo=timezone.utc)
  self.c={**luna.DEFAULT,'timezone':'Europe/Berlin','base_load_w':500}
 def rule(self,**patch):
  return consumption.validate({'kind':'consumption','start':'2026-10-30T17:00','end':'2026-10-30T19:00','kwh':1.5,'repeat':'daily',**patch},self.c,self.now)
 def energy(self,rows):return sum(r['kw']*(r['end']-r['start']).total_seconds()/3600 for r in rows)
 def test_daily_energy_and_one_occurrence(self):
  r=self.rule();xs=consumption.intervals([r],self.now,self.now+timedelta(days=3))
  self.assertAlmostEqual(self.energy(xs),4.5)
  self.assertEqual(len(consumption.upcoming([r],self.now)),1)
 def test_current_occurrence_is_the_only_visible_one(self):
  r=self.rule()
  now=datetime(2026,10,30,17,tzinfo=timezone.utc)
  rows=consumption.upcoming([r],now)
  self.assertEqual(len(rows),1)
  self.assertLess(consumption.stamp(rows[0]['start']),now)
  self.assertGreater(consumption.stamp(rows[0]['end']),now)
 def test_weekdays_and_overnight(self):
  r=self.rule(start='2026-10-30T23:00',end='2026-10-31T01:00',repeat='weekly',weekdays=[0,4],kwh=2)
  xs=consumption.expand(r,self.now,self.now+timedelta(days=8))
  self.assertEqual([x['start'][:10] for x in xs],['2026-10-30','2026-11-02','2026-11-06'])
  self.assertAlmostEqual(self.energy(consumption.intervals([r],self.now,self.now+timedelta(days=8))),6)
 def test_partial_holiday_and_overlapping_loads(self):
  a=self.rule();b=self.rule(kwh=2);h=self.rule(kind='holiday',start='2026-10-30T18:00',end='2026-10-30T20:00')
  xs=consumption.intervals([a,b,h],self.now,self.now+timedelta(days=1))
  self.assertAlmostEqual(self.energy(xs),1.75)
  prices=[{'start':self.now,'end':self.now+timedelta(days=1),'ct':40}]
  c={**self.c,'extra_load_kwh':100,'_consumption_rules':[a,b,h]}
  rows=dispatch.demand_rows(c,prices,self.now,self.now+timedelta(days=1))
  self.assertAlmostEqual(sum(r['gross_load_kw']*(r['end']-r['start']).total_seconds()/3600 for r in rows),12+1.75)
 def test_holiday_suppresses_once_and_recurring_not_hardware(self):
  r=self.rule(repeat='once');h=self.rule(kind='holiday',start='2026-10-30T09:00',end='2026-11-03T12:00')
  self.assertEqual(consumption.intervals([r,h],self.now,self.now+timedelta(days=1)),[])
  self.assertIsNone(manual.active([h],self.now+timedelta(hours=2)))
  self.assertTrue(consumption.upcoming([r,h],self.now)[1]['holiday_overlap'])
 def test_dst_recurring_uses_local_time_and_keeps_total_energy(self):
  now=datetime(2026,10,23,tzinfo=timezone.utc)
  r=consumption.validate({'kind':'consumption','start':'2026-10-24T01:00','end':'2026-10-24T04:00','kwh':3,'repeat':'daily'},self.c,now)
  start=datetime(2026,10,25,tzinfo=timezone.utc);end=start+timedelta(hours=4)
  xs=consumption.intervals([r],start-timedelta(hours=1),end)
  self.assertAlmostEqual(self.energy(xs),3)
  self.assertEqual((xs[0]['end']-xs[0]['start']).total_seconds(),4*3600)
 def test_edit_old_recurrence_and_do_not_expire_it(self):
  r=self.rule();later=self.now+timedelta(days=14)
  edited=consumption.validate({**r,'kwh':2},self.c,later)
  with tempfile.TemporaryDirectory() as tmp:
   f=Path(tmp);luna.write_json(f/'manual-orders.json',{'serial':'','rows':[edited]})
   self.assertEqual(manual.expire(f,later),[])
   self.assertEqual(len(manual.load(f,'',later)),1)
 def test_migration_idempotent_and_crash_safe(self):
  c={**self.c,'extra_load_kwh':1.5}
  with tempfile.TemporaryDirectory() as tmp:
   f=Path(tmp);luna.write_json(f/'config.json',c)
   consumption.migrate(f,c,self.now);consumption.migrate(f,c,self.now)
   data=json.loads((f/'manual-orders.json').read_text())
   self.assertEqual(len(data['rows']),1);self.assertEqual(data['rows'][0]['kwh'],1.5)
   self.assertEqual(json.loads((f/'config.json').read_text())['extra_load_kwh'],0)
 def test_planner_buys_more_for_extra_load_and_holiday_cancels_it(self):
  import joint
  c={**self.c,'timezone':'UTC','base_load_w':100,'battery_idle_w':0,'battery_floor_soc':0,'battery_capacity_kwh':10,'target_soc':90,'smart_discharge_enabled':True,'wear_ct_kwh':0,'min_saving_ct_kwh':0,'_consumption_rules':[]}
  n=self.now.replace(hour=0)
  prices=[{'start':n+timedelta(minutes=15*i),'end':n+timedelta(minutes=15*(i+1)),'ct':10 if i<24 else 60} for i in range(96)]
  r=consumption.validate({'kind':'consumption','start':'2026-10-30T17:00','end':'2026-10-30T19:00','kwh':3},c,n)
  h=consumption.validate({'kind':'holiday','start':'2026-10-30T00:00','end':'2026-10-31T00:00'},c,n)
  baseline=joint.plan(c,prices,n,0)['planned_kwh']
  extra=joint.plan({**c,'_consumption_rules':[r]},prices,n,0)['planned_kwh']
  holiday=joint.plan({**c,'_consumption_rules':[r,h]},prices,n,0)['planned_kwh']
  self.assertGreater(extra,baseline+2)
  self.assertAlmostEqual(holiday,baseline)
 def test_invalid_parameters(self):
  for patch in ({'kwh':-1},{'kwh':float('nan')},{'repeat':'weekly','weekdays':[]},{'repeat':'weekly','weekdays':[7]},{'end':'2026-10-30T16:00'}):
   with self.assertRaises(ValueError):self.rule(**patch)

if __name__=='__main__':unittest.main()

class PriceTipTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,10,30,10,tzinfo=timezone.utc)
  self.c={**luna.DEFAULT,'timezone':'Europe/Berlin'}
  self.data={'start':'2026-10-30T15:00','end':'2026-10-30T16:00','kwh':1.5}
  self.prices=[{'start':self.now+timedelta(hours=i),'end':self.now+timedelta(hours=i+1),'ct':20 if i==6 else 40} for i in range(13)]
 def test_cheaper_same_day_and_energy(self):
  tip=consumption.price_tip(self.data,self.c,self.prices,self.now)
  self.assertEqual(tip['state'],'better')
  self.assertEqual(tip['start'],'2026-10-30T16:00:00+00:00')
  self.assertAlmostEqual(tip['saving_eur'],.3)
 def test_gaps_negative_prices_and_no_future_invention(self):
  self.assertEqual(consumption.price_tip(self.data,self.c,[],self.now)['state'],'missing')
  prices=[{**p,'ct':-10 if i==6 else 40} for i,p in enumerate(self.prices)]
  self.assertAlmostEqual(consumption.price_tip(self.data,self.c,prices,self.now)['saving_eur'],.75)
  self.assertEqual(consumption.price_tip(self.data,self.c,[self.prices[4]],self.now)['state'],'good')
 def test_holiday_candidate_excluded(self):
  holiday=consumption.validate({'kind':'holiday','start':'2026-10-30T17:00','end':'2026-10-30T18:00'},self.c,self.now)
  self.assertEqual(consumption.price_tip(self.data,self.c,self.prices,self.now,[holiday])['state'],'good')
 def test_partial_tariff_weighting(self):
  data={**self.data,'start':'2026-10-30T16:30','end':'2026-10-30T17:30'}
  tip=consumption.price_tip(data,self.c,self.prices,self.now)
  self.assertAlmostEqual(tip['current_eur'],.45)

class DurationTemplateTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,10,30,14,0,45,tzinfo=timezone.utc)
  self.c={**luna.DEFAULT,'timezone':'Europe/Berlin'}
 def test_now_minute_input_preserves_duration_and_proposal(self):
  data={'kind':'consumption','start':'2026-10-30T15:00','duration_minutes':60,'kwh':1.5}
  normalized=consumption.with_duration(data,self.c,self.now)
  self.assertEqual(consumption.stamp(normalized['start']),self.now)
  self.assertEqual(consumption.stamp(normalized['end'])-self.now,timedelta(hours=1))
  prices=[{'start':self.now.replace(minute=0,second=0)+timedelta(hours=i),'end':self.now.replace(minute=0,second=0)+timedelta(hours=i+1),'ct':20+i} for i in range(9)]
  tip=consumption.price_tip(data,self.c,prices,self.now)
  self.assertIn(tip['state'],('better','good'));self.assertTrue(tip['suggestions'])
 def test_suggestions_span_day_and_include_global_best(self):
  now=self.now.replace(hour=0,minute=0,second=0)
  prices=[{'start':now+timedelta(hours=i),'end':now+timedelta(hours=i+1),'ct':10 if i==15 else 30+i%6} for i in range(23)]
  tip=consumption.price_tip({'start':'2026-10-30T09:00','duration_minutes':60,'kwh':1},self.c,prices,now)
  self.assertEqual(len(tip['suggestions']),4)
  self.assertTrue(any(o['cheapest'] and o['cost_eur']==.1 for o in tip['suggestions']))
  self.assertEqual(len(set(consumption.stamp(o['start']).astimezone(consumption.ZoneInfo('Europe/Berlin')).hour//6 for o in tip['suggestions'])),4)
 def test_template_crud_and_validation(self):
  data={'name':'Waschen','duration_minutes':90,'kwh':1.5}
  rows=consumption.template_change([],data);ident=rows[0]['id']
  rows=consumption.template_change(rows,{**data,'id':ident,'name':'Eco','kwh':.8})
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['kwh'],.8)
  self.assertEqual(consumption.template_change(rows,{'id':ident},delete=True),[])
  for patch in ({'name':''},{'duration_minutes':0},{'kwh':float('nan')}):
   with self.assertRaises(ValueError):consumption.template_change([],{**data,**patch})
 def test_duration_orders_keep_overlap_and_soc_limits(self):
  data={'kind':'hold','start':'2026-10-30T15:00','duration_minutes':60,'end_kind':'time'}
  rows=manual.upsert([],data,self.c,self.now)
  self.assertEqual(consumption.stamp(rows[0]['end'])-consumption.stamp(rows[0]['start']),timedelta(hours=1))
  with self.assertRaisesRegex(ValueError,'Überschneidung'):manual.upsert(rows,data,self.c,self.now)
