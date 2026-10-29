import tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch,Mock
import manual,luna,joint,web

class ManualTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,29,12,tzinfo=timezone.utc)
        self.c={**luna.DEFAULT,'expected_serial':'TEST','password':'pw','battery_capacity_kwh':10,'base_load_w':500,'smart_discharge_enabled':True,'target_soc':80,'charge_power_w':5000,'max_buy_ct_kwh':10,'battery_floor_soc':5,'battery_idle_w':0}
    def item(self,kind='charge',start=0,end=60,**extra):
        data={'kind':kind,'start':(self.now+timedelta(minutes=start)).isoformat(),'end':(self.now+timedelta(minutes=end)).isoformat(),'end_kind':'time',**extra}
        return manual.upsert([],data,self.c,self.now)[0]
    def test_overlap_and_boundary(self):
        row=self.item()
        with self.assertRaisesRegex(ValueError,'Überschneidung'):manual.upsert([row],self.item(start=30,end=90)|{'id':None},self.c,self.now)
        self.assertEqual(len(manual.upsert([row],self.item(start=60,end=120)|{'id':None},self.c,self.now)),2)
        self.assertEqual(len(manual.upsert([row],self.item('hold')|{'id':None},self.c,self.now)),2)
    def test_forever_and_edit(self):
        row=self.item('hold',end_kind='forever')
        self.assertIsNone(row['end'])
        edited=manual.upsert([row],{**row,'end_kind':'time','end':(self.now+timedelta(hours=1)).isoformat()},self.c,self.now)
        self.assertEqual(edited[0]['id'],row['id']);self.assertNotEqual(edited[0]['token'],row['token'])
    def test_dst_and_session_limit(self):
        with self.assertRaisesRegex(ValueError,'Zeitumstellung'):manual.local_time('2026-10-25T02:30','Europe/Berlin')
        with self.assertRaises(ValueError):self.item(end=121)
        with self.assertRaises(ValueError):self.item(end_kind='soc',target_soc=99)
    def test_persistent_completed_expired_serial(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);row=self.item()
            luna.write_json(folder/'manual-orders.json',{'serial':'TEST','rows':[row]})
            self.assertEqual(manual.load(folder,'TEST',self.now),[row])
            with self.assertRaises(ValueError):manual.load(folder,'OTHER',self.now)
            manual.complete(folder,row)
            self.assertEqual(manual.load(folder,'TEST',self.now),[])
            self.assertEqual(manual.expire(folder,self.now+timedelta(days=1)),[])
    def test_migration_preserves_existing_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp);until=(self.now+timedelta(hours=1)).isoformat()
            luna.write_json(f/'discharge-request.json',{'serial':'TEST','until':until})
            manual.migrate(f,'TEST',self.now)
            self.assertEqual(manual.load(f,'TEST',self.now)[0]['end'],until)
            self.assertIsNone(web.read(f/'discharge-request.json',{})['until'])
    def test_manual_decision_ignores_price_and_off_but_obeys_device(self):
        row=self.item();c={**self.c,'_orders':[row],'_orders_only':True}
        snap={'soc':40,'battery_status':2,'ac_charge_enabled':True}
        self.assertTrue(luna.decide(c,snap,[],self.now)[0])
        self.assertFalse(luna.decide(c,{**snap,'ac_charge_enabled':False},[],self.now)[0])
        self.assertFalse(luna.decide(c,{**snap,'soc':80},[],self.now)[0])
        self.assertFalse(luna.decide(c,snap,[],self.now+timedelta(hours=1))[0])
        self.assertFalse(luna.decide({**c,'_orders':[]},snap,[],self.now)[0])
    def test_planner_accounts_for_future_forced_charge_and_holds(self):
        prices=[{'start':self.now+timedelta(minutes=15*i),'end':self.now+timedelta(minutes=15*(i+1)),'ct':80} for i in range(32)]
        row=self.item(start=60,end=120,end_kind='soc',target_soc=60)
        hold=self.item('hold',start=0,end=180)
        c={**self.c,'_orders':[row,hold]}
        plan=joint.plan(c,prices,self.now,20)
        self.assertGreater(plan['planned_kwh'],3)
        self.assertTrue(all(t['discharge_kwh']==0 for t in plan['trace'] if datetime.fromisoformat(t['start'])<self.now+timedelta(hours=3)))
        self.assertTrue(all(w['manual'] for w in plan['charges']))
        self.assertTrue(all(datetime.fromisoformat(w['start'])>=self.now+timedelta(hours=1) for w in plan['charges']))
        self.assertLessEqual(max(t['end_kwh'] for t in plan['trace']),5.5+1e-6)
    def test_off_forecast_has_no_unrequested_price_holds_or_charges(self):
        prices=[{'start':self.now+timedelta(minutes=15*i),'end':self.now+timedelta(minutes=15*(i+1)),'ct':1 if i<4 else 100} for i in range(16)]
        c={**self.c,'_orders_only':True,'_orders':[self.item('hold',start=60,end=120)]}
        plan=joint.plan(c,prices,self.now,50)
        self.assertEqual(plan['planned_kwh'],0)
        self.assertGreater(plan['trace'][0]['discharge_kwh'],0)
    def test_smart_without_discharge_optimization_still_plans_manual_charge(self):
        prices=[{'start':self.now+timedelta(minutes=15*i),'end':self.now+timedelta(minutes=15*(i+1)),'ct':80} for i in range(20)]
        c={**self.c,'smart_discharge_enabled':False,'_orders':[self.item(start=60,end=120,end_kind='soc',target_soc=60)]}
        plan=joint.plan(c,prices,self.now,20)
        self.assertIsNotNone(plan);self.assertGreater(plan['planned_kwh'],0)
        self.assertGreater(plan['trace'][0]['discharge_kwh'],0)

    def test_api_persists_without_changing_smart(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp);app=web.Dashboard(f,start_worker=False)
            app.save_settings({k:v for k,v in self.c.items() if k!='mode'});luna.write_json(f/'commissioned.json',{'serial':'TEST'});app.mode='smart'
            app.action('manual-save',{'kind':'hold','end_kind':'forever','start':''})
            rows=manual.load(f,'TEST');self.assertEqual(len(rows),1);self.assertEqual(app.mode,'smart')
            app.action('manual-delete',{'id':rows[0]['id']});self.assertEqual(manual.load(f,'TEST'),[])
            self.assertEqual(app.mode,'smart')
    def test_off_worker_starts_due_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp);app=web.Dashboard(f,start_worker=False);app.save_settings({k:v for k,v in self.c.items() if k!='mode'})
            luna.write_json(f/'commissioned.json',{'serial':'TEST'})
            now=datetime.now(timezone.utc)
            rows=manual.upsert([],{'kind':'charge','start':'','end_kind':'soc','target_soc':70},self.c,now)
            luna.write_json(f/'manual-orders.json',{'serial':'TEST','rows':rows})
            with patch.object(app.closed,'wait',side_effect=[False,True]),patch.object(app,'launch') as launch:
                app.worker()
            launch.assert_called_once_with('run');self.assertEqual(app.mode,'off')

if __name__=='__main__':unittest.main()

class ManualRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_off_soc_completion_stops_and_does_not_restart(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);now=datetime.now(timezone.utc)
            c={**luna.DEFAULT,'expected_serial':'TEST','password':'pw','mode':'auto'}
            luna.write_json(folder/'config.json',c);luna.write_json(folder/'commissioned.json',{'serial':'TEST'})
            rows=manual.upsert([],{'kind':'charge','start':'','end_kind':'soc','target_soc':60},c,now)
            luna.write_json(folder/'manual-orders.json',{'serial':'TEST','rows':rows})
            count=[0]
            async def snapshot():
                count[0]+=1
                if count[0]>4:raise AssertionError('Completed order did not exit')
                return {'soc':40 if count[0]<3 else 60,'battery_status':2,'battery_power_w':1000,'ac_charge_enabled':True,'max_charge_power_w':5000}
            hw=SimpleNamespace(device=SimpleNamespace(serial_number='TEST'),connect=AsyncMock(),login=AsyncMock(),snapshot=snapshot,charge=AsyncMock(),stop_charge=AsyncMock(),close=AsyncMock())
            async def wait(aw,timeout):
                if getattr(getattr(aw,'cr_code',None),'co_name',None)=='wait':aw.close();raise TimeoutError()
                return await aw
            with patch('luna.Huawei',return_value=hw),patch('luna.asyncio.wait_for',side_effect=wait),patch('discharge.sync',new=AsyncMock()),patch('luna.emit') as emit:
                await luna.operate(SimpleNamespace(command='run',execute=True,orders_only=True),c,folder)
            hw.charge.assert_awaited_once();hw.stop_charge.assert_awaited_once()
            self.assertEqual(manual.load(folder,'TEST'),[])
            self.assertTrue(any(x.args[0]=='manual_completed' for x in emit.call_args_list))

    async def test_forever_hold_and_removal_restores_original_power(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from discharge import sync
        from huawei_solar import register_names as rn
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp);c={**luna.DEFAULT,'expected_serial':'TEST'}
            rows=manual.upsert([],{'kind':'hold','start':'','end_kind':'forever'},c)
            luna.write_json(f/'manual-orders.json',{'serial':'TEST','rows':rows})
            power=[3456]
            async def read(names):return {rn.STORAGE_MAXIMUM_DISCHARGING_POWER:SimpleNamespace(value=power[0])}
            async def write(name,value):power[0]=value
            hw=SimpleNamespace(device=SimpleNamespace(serial_number='TEST',batch_update=read),write=AsyncMock(side_effect=write))
            await sync(hw,f);self.assertEqual(power[0],0)
            await sync(hw,f,smart_hold=False);self.assertEqual(power[0],0)
            luna.write_json(f/'manual-orders.json',{'serial':'TEST','rows':[]})
            await sync(hw,f);self.assertEqual(power[0],3456)
