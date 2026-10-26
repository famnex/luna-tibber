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
