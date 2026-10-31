import unittest
from test_consumption_advice import AdviceTests

class BreakdownTests(unittest.TestCase):
 def fixture(self):
  f=AdviceTests();f.setUp();return f
 def check(self,result,kwh):
  for row in result['suggestions']:
   self.assertAlmostEqual(sum(row['sources_kwh'].values()),kwh,places=8)
   self.assertTrue(all(v>=-1e-8 for v in row['sources_kwh'].values()))
   self.assertAlmostEqual(row['usage_cost_eur']+row['later_extra_eur']+row['plan_adjustment_eur'],row['cost_eur'],places=9)
 def test_battery_and_future_costs_remain_distinct(self):
  f=self.fixture();r=f.compare(mode='off');self.check(r,1.5)
  row=r['suggestions'][0]
  self.assertGreater(row['sources_kwh']['battery'],0)
  self.assertGreater(row['later_extra_eur'],0)
 def test_hold_is_grid_funded_not_battery_funded(self):
  f=self.fixture();r=f.compare();self.check(r,1.5)
  row=r['suggestions'][0]
  self.assertGreater(row['hold_minutes'],0)
  self.assertAlmostEqual(row['sources_kwh']['battery'],0)
  self.assertAlmostEqual(row['sources_kwh']['grid'],1.5)
 def test_solar_and_no_double_count(self):
  f=self.fixture();f.c.update(pv_enabled=True,_pv={'rows':[{**p,'kw':4} for p in f.prices]})
  r=f.compare();self.check(r,1.5)
  row=r['suggestions'][0]
  self.assertAlmostEqual(row['sources_kwh']['pv'],1.5)
  self.assertAlmostEqual(row['usage_cost_eur'],0)
 def test_hourly_estimates_preserve_energy_and_cost_balance(self):
  f=self.fixture();f.c.update(_comparison_fast=True,_comparison_hourly=True)
  self.check(f.compare(),1.5)

if __name__=='__main__':unittest.main()
