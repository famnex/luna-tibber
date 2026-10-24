import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from discharge import sync,read
from luna import write_json
from huawei_solar import register_names as rn

class DischargeTests(unittest.IsolatedAsyncioTestCase):
    async def test_unchanged_hold_uses_one_read_and_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            write_json(folder/'discharge-restore.json',{'serial':'test','original_w':4000})
            hw=SimpleNamespace(device=SimpleNamespace(serial_number='test',batch_update=AsyncMock(return_value={rn.STORAGE_MAXIMUM_DISCHARGING_POWER:SimpleNamespace(value=0)})),write=AsyncMock())
            await sync(hw,folder,smart_hold=True)
            hw.device.batch_update.assert_awaited_once();hw.write.assert_not_awaited()

    async def test_lock_restart_release_restores_exact_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);now=datetime.now(timezone.utc)
            write_json(folder/'discharge-request.json',{'serial':'test','until':(now+timedelta(hours=1)).isoformat()})
            power=[3456]
            async def read_power(names):return {rn.STORAGE_MAXIMUM_DISCHARGING_POWER:SimpleNamespace(value=power[0])}
            async def write(name,v):power[0]=v
            hw=SimpleNamespace(device=SimpleNamespace(serial_number='test',batch_update=read_power),write=AsyncMock(side_effect=write))
            await sync(hw,folder,now)
            self.assertEqual(power[0],0)
            self.assertEqual(read(folder/'discharge-restore.json')['original_w'],3456)
            await sync(hw,folder,now)
            self.assertEqual(hw.write.call_count,1)
            await sync(hw,folder,now+timedelta(hours=2))
            self.assertEqual(power[0],3456)
            self.assertFalse((folder/'discharge-restore.json').exists())
    async def test_failed_write_retains_restore_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);now=datetime.now(timezone.utc)
            write_json(folder/'discharge-request.json',{'serial':'test','until':(now+timedelta(hours=1)).isoformat()})
            hw=SimpleNamespace(device=SimpleNamespace(serial_number='test',batch_update=AsyncMock(return_value={rn.STORAGE_MAXIMUM_DISCHARGING_POWER:SimpleNamespace(value=4000)})),write=AsyncMock(side_effect=RuntimeError('failed')))
            with self.assertRaises(RuntimeError):await sync(hw,folder,now)
            self.assertTrue((folder/'discharge-restore.json').exists())
            hw.device.serial_number='other'
            with self.assertRaises(ValueError):await sync(hw,folder,now+timedelta(hours=2))
            self.assertEqual(hw.write.call_count,1)
    async def test_foreign_change_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            write_json(folder/'discharge-restore.json',{'serial':'test','original_w':4000})
            hw=SimpleNamespace(device=SimpleNamespace(serial_number='test',batch_update=AsyncMock(return_value={rn.STORAGE_MAXIMUM_DISCHARGING_POWER:SimpleNamespace(value=2000)})),write=AsyncMock())
            with self.assertRaises(ValueError):await sync(hw,folder)
            hw.write.assert_not_called()
    async def test_manual_hold_takes_priority_over_smart_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);now=datetime.now(timezone.utc);power=[4000]
            async def read_power(names):return {rn.STORAGE_MAXIMUM_DISCHARGING_POWER:SimpleNamespace(value=power[0])}
            async def write(name,v):power[0]=v
            hw=SimpleNamespace(device=SimpleNamespace(serial_number='test',batch_update=read_power),write=AsyncMock(side_effect=write))
            await sync(hw,folder,now,smart_hold=True)
            self.assertEqual(read(folder/'discharge-status.json')['source'],'smart')
            write_json(folder/'discharge-request.json',{'serial':'test','until':(now+timedelta(hours=1)).isoformat()})
            await sync(hw,folder,now,smart_hold=False)
            self.assertEqual(power[0],0)
            self.assertEqual(read(folder/'discharge-status.json')['source'],'manual')
            await sync(hw,folder,now+timedelta(hours=2),smart_hold=False)
            self.assertEqual(power[0],4000)
