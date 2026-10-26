import unittest
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
import luna

class MeterTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_and_partial_errors(self):
        names=['METER_STATUS','METER_TYPE','POWER_METER_ACTIVE_POWER','GRID_EXPORTED_ENERGY','GRID_ACCUMULATED_ENERGY','INPUT_POWER','ACTIVE_POWER','ACCUMULATED_YIELD_ENERGY']
        fake=SimpleNamespace(register_names=SimpleNamespace(**{n:n for n in names}))
        async def read(keys):
            if keys[0]=='METER_TYPE':raise RuntimeError('private device error')
            return {keys[0]:SimpleNamespace(value=42,unit='W')}
        hw=luna.Huawei({});hw.device=SimpleNamespace(batch_update=AsyncMock(side_effect=read));hw.login=AsyncMock();hw.write=AsyncMock()
        with patch.dict('sys.modules',{'huawei_solar':fake}):rows=await hw.meter_test()
        self.assertEqual(len(rows),8);self.assertFalse(rows[1]['ok']);self.assertTrue(rows[2]['ok'])
        self.assertEqual(rows[1]['error'],'RuntimeError');hw.login.assert_not_called();hw.write.assert_not_called()

    async def test_diagnostic_failure_does_not_stop_snapshot_and_is_throttled(self):
        from huawei_solar import register_names as rn
        fields={rn.STORAGE_STATE_OF_CAPACITY:50,rn.STORAGE_CHARGE_DISCHARGE_POWER:0,
                rn.STORAGE_RUNNING_STATUS:2,rn.STORAGE_MAXIMUM_CHARGE_POWER:5000,
                rn.STORAGE_CHARGE_FROM_GRID_FUNCTION:True}
        async def read(keys):
            if rn.METER_STATUS in keys:raise TimeoutError()
            return {k:SimpleNamespace(value=fields[k]) for k in keys}
        hw=luna.Huawei({});hw.device=SimpleNamespace(batch_update=AsyncMock(side_effect=read))
        a=await hw.snapshot();b=await hw.snapshot()
        self.assertEqual(a['soc'],50);self.assertFalse(a['meter']['valid']);self.assertNotIn('meter',b)
        self.assertEqual(hw.device.batch_update.await_count,3)

    async def test_meter_direction_and_restart_throttle(self):
        import tempfile
        from pathlib import Path
        from huawei_solar import register_names as rn
        fields={rn.STORAGE_STATE_OF_CAPACITY:50,rn.STORAGE_CHARGE_DISCHARGE_POWER:-370,
                rn.STORAGE_RUNNING_STATUS:2,rn.STORAGE_MAXIMUM_CHARGE_POWER:5000,
                rn.STORAGE_CHARGE_FROM_GRID_FUNCTION:True,rn.POWER_METER_ACTIVE_POWER:-5,
                rn.ACTIVE_POWER:368,rn.INPUT_POWER:7,rn.METER_STATUS:1,
                rn.GRID_ACCUMULATED_ENERGY:19443.3,rn.GRID_EXPORTED_ENERGY:5825.02,
                rn.STORAGE_MAXIMUM_DISCHARGING_POWER:5000}
        async def read(keys):return {k:SimpleNamespace(value=fields[k]) for k in keys}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'meter-sample-at.json'
            hw=luna.Huawei({});hw.meter_sample_path=path;hw.device=SimpleNamespace(batch_update=AsyncMock(side_effect=read))
            result=await hw.snapshot();self.assertEqual(result['meter']['house_w'],373);self.assertTrue(result['meter']['valid'])
            again=luna.Huawei({});again.meter_sample_path=path;again.device=hw.device
            self.assertNotIn('meter',await again.snapshot())
