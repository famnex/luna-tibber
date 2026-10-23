import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import luna
from huawei_solar import register_names as rn, register_values as rv
from huawei_solar.registers import REGISTERS

class LogicTests(unittest.TestCase):
    def setUp(self):
        self.c = dict(luna.DEFAULT)
        self.now = datetime(2026,10,22,18,0,tzinfo=timezone.utc)
        self.c.update(use_start_hour=6,use_end_hour=9)
        self.s = {"soc": 61, "battery_status": 2, "ac_charge_enabled": True}
        self.p = [{"start": self.now, "end": self.now+timedelta(minutes=15), "ct": 15}]
        start = datetime(2026,10,23,4,0,tzinfo=timezone.utc)
        self.p += [{"start":start+timedelta(minutes=15*i), "end":start+timedelta(minutes=15*(i+1)), "ct":30} for i in range(12)]
    def test_economics_and_missing_prices(self):
        plan=luna.economics_plan(self.c,self.p,self.now)
        self.assertTrue(plan["ok"])
        self.assertAlmostEqual(plan["effective_ct_kwh"],15/.85)
        self.assertFalse(luna.economics_plan(self.c,self.p[:-1],self.now)["ok"])
        self.assertFalse(luna.economics_plan({**self.c,"wear_ct_kwh":20},self.p,self.now)["ok"])
        self.assertFalse(luna.economics_plan(self.c,self.p,self.p[1]["start"])["ok"])
    def test_price_and_soc(self):
        self.assertTrue(luna.decide(self.c,self.s,self.p,self.now)[0])
        self.s['soc']=80
        self.assertFalse(luna.decide(self.c,self.s,self.p,self.now)[0])
        self.s['soc']=61
        self.p[0]['ct']=21
        self.assertFalse(luna.decide(self.c,self.s,self.p,self.now)[0])
    def test_gap_expiry_and_interval_margin(self):
        self.assertFalse(luna.decide(self.c,self.s,[],self.now)[0])
        for minutes in (13,15,60):
            self.assertFalse(luna.decide(self.c,self.s,self.p,self.now+timedelta(minutes=minutes))[0])
    def test_fault_and_disabled(self):
        self.s['battery_status']=3
        self.assertFalse(luna.decide(self.c,self.s,self.p,self.now)[0])
        self.s['battery_status']=2
        self.s['ac_charge_enabled']=False
        self.assertFalse(luna.decide(self.c,self.s,self.p,self.now)[0])
    def test_invalid_values(self):
        for v in [float('nan'),float('inf'),-1,101,True]:
            with self.assertRaises(ValueError):
                luna.validate({**self.c,'target_soc':v})
    def test_utc_dst_slots(self):
        a=datetime.fromisoformat('2026-10-25T02:00:00+02:00').astimezone(timezone.utc)
        b=datetime.fromisoformat('2026-10-25T02:00:00+01:00').astimezone(timezone.utc)
        self.assertEqual((b-a).total_seconds(),3600)
        slots=[{'start':a,'end':a+timedelta(minutes=15),'ct':10}, {'start':b,'end':b+timedelta(minutes=15),'ct':40}]
        self.assertEqual(luna.decide(self.c,self.s,slots,a)[2]["ct"],10)
        self.assertFalse(luna.decide(self.c,self.s,slots,b)[0])

class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_finite_duration_written_before_start(self):
        hw=luna.Huawei(dict(luna.DEFAULT))
        hw.device=SimpleNamespace(set=AsyncMock(return_value=True))
        await hw.charge(1000,2)
        calls=hw.device.set.call_args_list
        self.assertEqual(calls[-1].args,(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,rv.StorageForcibleChargeDischarge.CHARGE))
        self.assertIn((rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,2),[c.args for c in calls[:-1]])
        for call in calls:
            reg=REGISTERS[call.args[0]]
            self.assertTrue(reg.writeable)
            reg.encode(call.args[1])
    async def test_partial_write_does_not_start(self):
        hw=luna.Huawei(dict(luna.DEFAULT))
        hw.device=SimpleNamespace(set=AsyncMock(side_effect=[True,False]))
        with self.assertRaises(RuntimeError):
            await hw.charge(1000,2)
        self.assertEqual(hw.device.set.call_count,2)
    async def test_failed_charge_attempt_stops_and_no_commissioning(self):
        c={**luna.DEFAULT,'expected_serial':'TEST','password':'fake'}
        fake=SimpleNamespace(device=SimpleNamespace(serial_number='TEST'), connect=AsyncMock(),
            snapshot=AsyncMock(return_value={'soc':61,'ac_charge_enabled':True,'battery_status':2,'max_charge_power_w':5000}),
            login=AsyncMock(),charge=AsyncMock(side_effect=RuntimeError('write failed')),
            stop_charge=AsyncMock(), close=AsyncMock())
        with tempfile.TemporaryDirectory() as folder,patch('luna.Huawei',return_value=fake):
            with self.assertRaises(RuntimeError):
                await luna.operate(SimpleNamespace(command='charge-test',execute=True),c,Path(folder))
            fake.stop_charge.assert_awaited_once()
            self.assertFalse((Path(folder)/'commissioned.json').exists())
            self.assertFalse((Path(folder)/'pending-charge.json').exists())
    async def test_probe_never_logs_in_or_writes(self):
        fake=SimpleNamespace(device=SimpleNamespace(serial_number="TEST",model_name="SUN2000-5KTL-M1"),connect=AsyncMock(),snapshot=AsyncMock(return_value={}),login=AsyncMock(),close=AsyncMock(),stop_charge=AsyncMock())
        with tempfile.TemporaryDirectory() as folder,patch('luna.Huawei',return_value=fake):
            await luna.operate(SimpleNamespace(command='probe',execute=False),dict(luna.DEFAULT),Path(folder))
        fake.login.assert_not_awaited()
        fake.stop_charge.assert_not_awaited()
    async def test_stop_works_without_telemetry(self):
        fake=SimpleNamespace(connect=AsyncMock(),snapshot=AsyncMock(side_effect=RuntimeError('offline')),
            login=AsyncMock(),stop_charge=AsyncMock(),close=AsyncMock())
        with tempfile.TemporaryDirectory() as folder,patch('luna.Huawei',return_value=fake):
            await luna.operate(SimpleNamespace(command='stop',execute=True),dict(luna.DEFAULT),Path(folder))
        fake.snapshot.assert_not_awaited()
        fake.stop_charge.assert_awaited_once()

    async def test_auto_requires_commissioning(self):
        fake=SimpleNamespace(device=SimpleNamespace(serial_number='TEST'),connect=AsyncMock(),snapshot=AsyncMock(return_value={}),login=AsyncMock(),close=AsyncMock(),charge=AsyncMock())
        with tempfile.TemporaryDirectory() as folder,patch('luna.Huawei',return_value=fake):
            with self.assertRaises(ValueError):
                await luna.operate(SimpleNamespace(command='run',execute=True),{**luna.DEFAULT,'mode':'auto'},Path(folder))
        fake.charge.assert_not_awaited()

if __name__=='__main__': unittest.main()
