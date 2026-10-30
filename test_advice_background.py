import time
import unittest
from test_consumption_advice import AdviceTests
from consumption_advice import BackgroundAdvice

class BackgroundTests(unittest.TestCase):
 def fixture(self):
  f=AdviceTests();f.setUp();return f
 def test_job_returns_immediately_then_same_result_is_polled(self):
  f=self.fixture();runner=BackgroundAdvice();start=time.monotonic()
  response=runner.get(f.data,f.c,f.prices,f.telemetry,'smart',f.now)
  self.assertLess(time.monotonic()-start,2)
  self.assertEqual(response['state'],'pending');token=response['job']
  busy=runner.get(f.data,f.c,f.prices,f.telemetry,'smart',f.now)
  self.assertEqual(busy['state'],'busy')
  for _ in range(200):
   result=runner.poll(token)
   if result['state']!='pending':break
   time.sleep(.05)
  self.assertIn(result['state'],('good','better'))
  self.assertEqual(result,runner.poll(token))
  self.assertEqual(runner.poll('unknown')['state'],'unavailable')
 def test_deadline_releases_busy_state_without_browser_polling(self):
  f=self.fixture();runner=BackgroundAdvice(timeout=.001)
  response=runner.get(f.data,f.c,f.prices,f.telemetry,'smart',f.now)
  time.sleep(.3)
  result=runner.poll(response['job'])
  self.assertIn(result['state'],('good','better'))
  self.assertTrue(result['suggestions'])
  self.assertEqual(result['basis'],'tariff')
  self.assertIn('noch nicht berücksichtigt',result['message'])
  self.assertIsNotNone(runner.job['result'])

if __name__=='__main__':unittest.main()
