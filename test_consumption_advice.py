import copy,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import consumption_advice as advice
import consumption,joint,luna

class AdviceTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,10,30,8,tzinfo=timezone.utc)
  self.c={**luna.DEFAULT,'timezone':'UTC','battery_capacity_kwh':10,'battery_floor_soc':0,'battery_idle_w':0,'target_soc':90,'base_load_w':100,'roundtrip_efficiency':1,'wear_ct_kwh':0,'min_saving_ct_kwh':0,'smart_discharge_enabled':True,'pv_enabled':False,'_consumption_rules':[],'_orders':[]}
  self.prices=[{'start':self.now+timedelta(hours=i),'end':self.now+timedelta(hours=i+1),'ct':70 if i>=9 else 30} for i in range(16)]
  self.telemetry={'time':self.now.isoformat(),'soc':15}
  self.data={'start':self.now.isoformat(),'duration_minutes':60,'kwh':1.5}
 def compare(self,c=None,mode='smart',data=None):
  return advice.compare(data or self.data,c or self.c,self.prices,self.telemetry,mode,self.now)
 def test_later_grid_cost_is_not_free_battery_energy(self):
  result=self.compare(mode='off');now=result['suggestions'][0]
  self.assertGreater(now['cost_eur'],.45)
  self.assertGreater(now['later_extra_eur'],.4)
  self.assertFalse(now['automatic_hold'])
 def test_smart_can_protect_energy_for_later(self):
  smart=self.compare();off=self.compare(mode='off')
  self.assertLess(smart['current_eur'],off['current_eur'])
  first=smart['suggestions'][0]
  self.assertTrue(first['automatic_hold']);self.assertGreater(first['hold_minutes'],0)
 def test_pv_window_reduces_incremental_cost(self):
  c={**self.c,'pv_enabled':True,'_pv':{'rows':[{**r,'kw':4 if i in (4,5) else 0} for i,r in enumerate(self.prices)]}}
  result=self.compare(c);best=next(r for r in result['suggestions'] if r['cheapest'])
  self.assertEqual(consumption.stamp(best['start']).hour,12)
  self.assertGreater(best['pv_direct_kwh'],1)
  self.assertLess(best['cost_eur'],result['current_eur'])
 def test_existing_entry_is_replaced_in_comparison_not_added_twice(self):
  existing=consumption.validate({**self.data,'kind':'consumption','end':(self.now+timedelta(hours=1)).isoformat()},self.c,self.now)
  actual=self.compare({**self.c,'_consumption_rules':[existing]},data={**self.data,'id':existing['id']})
  expected=self.compare()
  self.assertAlmostEqual(actual['current_eur'],expected['current_eur'])
 def test_manual_hold_remains_in_off_simulation(self):
  hold={'kind':'hold','start':self.now.isoformat(),'end':(self.now+timedelta(hours=3)).isoformat()}
  result=self.compare({**self.c,'_orders':[hold]},mode='off')
  first=result['suggestions'][0]
  self.assertGreater(first['hold_minutes'],0);self.assertFalse(first['automatic_hold'])
 def test_no_state_mutation_and_bill_equals_trace(self):
  original=copy.deepcopy(self.c)
  self.compare()
  self.assertEqual(original,self.c)
  plan=joint.plan({**self.c,'_comparison':True},self.prices,self.now,15)
  self.assertAlmostEqual(plan['total_cost_eur'],sum(r['cost_eur'] for r in plan['trace']))
 def test_stale_soc_and_price_gaps_do_not_invent_costs(self):
  t={**self.telemetry,'time':(self.now-timedelta(seconds=91)).isoformat()}
  self.assertEqual(advice.compare(self.data,self.c,self.prices,t,'smart',self.now)['state'],'unavailable')
  result=advice.compare(self.data,self.c,self.prices[1:],self.telemetry,'smart',self.now)
  self.assertNotIn('current_eur',result)
 def test_cache_uses_inputs_and_rejects_stale_measurement(self):
  cache=advice.AdviceCache()
  with patch.object(advice,'compare',wraps=advice.compare) as compute:
   first=cache.get(self.data,self.c,self.prices,self.telemetry,'smart',self.now)
   second=cache.get(self.data,self.c,self.prices,self.telemetry,'smart',self.now)
   self.assertEqual(first,second);self.assertEqual(compute.call_count,1)
   stale={**self.telemetry,'time':(self.now-timedelta(seconds=91)).isoformat()}
   self.assertEqual(cache.get(self.data,self.c,self.prices,stale,'smart',self.now)['state'],'unavailable')
 def test_disabled_smart_optimisation_is_not_silently_enabled(self):
  result=self.compare({**self.c,'smart_discharge_enabled':False})
  self.assertEqual(result['state'],'unavailable')
  off=self.compare({**self.c,'smart_discharge_enabled':False},mode='off')
  self.assertIn(off['state'],('good','better'))
 def test_missing_pv_is_labelled(self):
  result=self.compare({**self.c,'pv_enabled':True,'_pv':{'rows':[]}})
  self.assertFalse(result['pv_available']);self.assertIn('ohne PV gerechnet',result['message'])

if __name__=='__main__':unittest.main()
