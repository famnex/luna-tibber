"""Fast preview preserves economic inputs and never coarsens live planning."""
import unittest
from unittest.mock import patch
from test_consumption_advice import AdviceTests
import joint

class FastAdviceTests(AdviceTests):
 def setUp(self):
  super().setUp();self.c['_comparison_fast']=True
 def test_fast_candidate_count_is_bounded(self):
  result=self.compare()
  self.assertLessEqual(result['evaluated'],7)
  self.assertIn('Schnellschätzung',result['message'])
 def test_live_grid_unchanged_even_if_fast_flag_present(self):
  with patch.object(joint,'_values',wraps=joint._values) as values:
   joint.plan(self.c,self.prices,self.now,15)
   self.assertTrue(values.called)
   self.assertTrue(all(call.kwargs.get('knots',81)==81 for call in values.call_args_list))
 def test_preview_uses_smaller_grid(self):
  with patch.object(joint,'_values',wraps=joint._values) as values:
   self.compare()
   self.assertTrue(all(call.kwargs.get('knots',81)==21 for call in values.call_args_list))

if __name__=='__main__':unittest.main()
