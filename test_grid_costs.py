import tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from grid_costs import GridCosts

class GridCostTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.folder=Path(self.tmp.name);self.g=GridCosts(self.folder)
  self.c={'expected_serial':'ABC','timezone':'Europe/Berlin'}
  self.start=datetime(2026,11,10,10,tzinfo=timezone.utc)
 def sample(self,minutes,value,prices):
  self.g.record(self.c,{'meter':{'valid':True,'measured_at':(self.start+timedelta(minutes=minutes)).isoformat(),'import_kwh':value}},prices)
 def price(self,a,b,ct):return dict(start=self.start+timedelta(minutes=a),end=self.start+timedelta(minutes=b),ct=ct)
 def test_weighted_actual_import_and_persistence(self):
  prices=[self.price(0,5,20),self.price(5,10,50)]
  self.sample(0,100,prices);self.sample(5,101,prices);self.sample(10,103,prices);self.sample(10,103,prices)
  row=GridCosts(self.folder).summary(self.c,self.start+timedelta(minutes=10))['periods']['today']
  self.assertAlmostEqual(row['kwh'],3);self.assertAlmostEqual(row['eur'],1.2);self.assertAlmostEqual(row['ct_kwh'],40)
  self.assertLess(row['coverage_pct'],100)
 def test_gaps_resets_and_missing_prices_not_filled(self):
  p=[self.price(0,60,20)]
  self.sample(0,100,p);self.sample(20,101,p);self.sample(25,0,p);self.sample(30,1,[])
  self.assertEqual(self.g.summary(self.c,self.start+timedelta(minutes=30))['periods']['today']['hours'],0)
 def test_negative_prices_zero_usage_and_device_change(self):
  p=[self.price(0,60,-10)]
  self.sample(0,0,p);self.sample(5,0,p)
  self.assertIsNone(self.g.summary(self.c,self.start+timedelta(minutes=5))['periods']['today']['ct_kwh'])
  self.sample(10,1,p)
  self.assertEqual(self.g.summary(self.c,self.start+timedelta(minutes=10))['periods']['today']['ct_kwh'],-10)
  self.assertEqual(self.g.summary(dict(self.c,expected_serial='OTHER'))['periods']['today']['hours'],0)
 def test_price_boundary_allocation(self):
  p=[self.price(0,2,20),self.price(2,5,50)]
  self.sample(0,0,p);self.sample(5,1,p)
  self.assertAlmostEqual(self.g.summary(self.c,self.start+timedelta(minutes=5))['periods']['today']['ct_kwh'],38)
