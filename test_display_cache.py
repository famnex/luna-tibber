import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
import luna,web

class DisplayCacheTests(unittest.TestCase):
 def test_restart_partial_and_serial(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)
   luna.write_json(folder/'config.json',{'expected_serial':'ABC'})
   app=web.Dashboard(folder,start_worker=False)
   event={'time':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),'soc':48.,'battery_power_w':-350.}
   app.remember_measurement(event)
   app.remember_measurement({'time':datetime.now(timezone.utc).isoformat(),'soc':None})
   self.assertEqual(app.display_measurement(app.config()),event)
   restored=web.Dashboard(folder,start_worker=False)
   self.assertEqual(restored.display_measurement(restored.config()),event)
   self.assertEqual(restored.telemetry,{})
   self.assertEqual(restored.display_measurement({'expected_serial':'OTHER'}),{})

 def test_startup_recovers_old_device_sample_without_planning(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)
   sample={'time':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),'soc':57,'battery_power_w':0}
   luna.write_json(folder/'config.json',{'expected_serial':'ABC'})
   luna.write_json(folder/'device.json',dict(sample,serial='ABC'))
   app=web.Dashboard(folder,start_worker=False)
   self.assertEqual(app.startup_snapshot()['measurement'],sample)
   self.assertEqual(app.telemetry,{})
   luna.write_json(folder/'config.json',{'expected_serial':'OTHER'})
   self.assertEqual(app.startup_snapshot()['measurement'],{})
