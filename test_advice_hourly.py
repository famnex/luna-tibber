import unittest
from datetime import timedelta
from test_consumption_advice import AdviceTests
from consumption_advice import hourly_prices

class HourlyAdviceTests(AdviceTests):
 def setUp(self):
  super().setUp();self.c.update(_comparison_fast=True,_comparison_hourly=True)
 def test_hourly_starts_are_evaluated(self):
  result=self.compare()
  self.assertGreaterEqual(result['evaluated'],16)
  self.assertTrue(result['estimate'])
  self.assertIn('gemittelte Stundenpreise',result['message'])
 def test_weighted_partial_hour_and_gap(self):
  now=self.now+timedelta(minutes=15)
  rows=[{'start':self.now+timedelta(minutes=15*i),'end':self.now+timedelta(minutes=15*(i+1)),'ct':10*i} for i in range(4)]
  result=hourly_prices(rows,now)
  self.assertEqual(len(result),1)
  self.assertEqual(result[0]['ct'],20)
  self.assertEqual(result[0]['start'],now)
  gap=hourly_prices(rows[2:],now)
  self.assertEqual(gap,rows[2:])

if __name__=='__main__':unittest.main()
