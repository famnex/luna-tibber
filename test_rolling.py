import unittest,math,tempfile
from pathlib import Path
from unittest.mock import Mock
from datetime import datetime,timedelta,timezone
import luna,joint,smart,dispatch
from price_cache import planning_end,get,revision,poll_interval

class RollingTests(unittest.TestCase):
    def case(self,pv=False):
        now=datetime(2026,10,27,13,5,tzinfo=timezone.utc)
        start=now.replace(minute=0)
        c={**luna.DEFAULT,'timezone':'UTC','pv_enabled':pv,'smart_discharge_enabled':True,
           'battery_capacity_kwh':10,'target_soc':95,'charge_power_w':5000,'base_load_w':500,
           'max_buy_ct_kwh':35,'roundtrip_efficiency':.85,'min_saving_ct_kwh':2,
           'battery_idle_w':0,'morning_buffer_pct':0}
        rows=[{'start':start+timedelta(minutes=15*i),'end':start+timedelta(minutes=15*(i+1)),
               'ct':27 if i==0 else 28 if i<44 else 37} for i in range(140)]
        state={'soc':20,'battery_status':2,'ac_charge_enabled':True,'max_charge_power_w':5000}
        return c,rows,now,state
    def test_publication_opens_remaining_daytime_window_and_controller(self):
        c,p,n,s=self.case()
        before=smart.plan(c,p[:44],n,s['soc']);self.assertEqual(before['planned_kwh'],0)
        after=smart.plan(c,p,n,s['soc']);first=after['windows'][0]
        self.assertEqual(first['start'],n.isoformat());self.assertEqual(first['ct'],27)
        self.assertGreater(first['battery_kwh'],0);self.assertLessEqual(first['battery_kwh'],5/6+1e-8)
        self.assertEqual(datetime.fromisoformat(after['joint']['plan_end']),p[-1]['end'])
        self.assertTrue(luna.decide(c,s,p,n)[0])
        self.assertEqual(dispatch.plan(c,p,n,s['soc'])['windows'],after['joint']['windows'])
    def test_short_window_partial_charge_only_when_future_published(self):
        c,p,n,s=self.case();c['max_buy_ct_kwh']=27
        q=joint.plan(c,p,n,s['soc']);self.assertEqual(len(q['charges']),1)
        first=q['charges'][0]
        self.assertGreater(first['battery_kwh'],.5);self.assertLess(first['battery_kwh'],1)
        self.assertLessEqual(datetime.fromisoformat(first['end']),p[0]['end'])
        self.assertTrue(luna.decide(c,s,p,n)[0])
    def test_price_cap_and_device_constraints_remain(self):
        c,p,n,s=self.case();c['max_buy_ct_kwh']=20
        blocked=smart.plan(c,p,n,20)
        self.assertEqual(blocked['planned_kwh'],0)
        self.assertIn('27,00 ct/kWh > Kaufgrenze 20,00 ct/kWh',blocked['reason'])
        self.assertFalse(luna.decide(c,s,p,n)[0])
        c['max_buy_ct_kwh']=35
        for state in ({**s,'soc':95},{**s,'battery_status':0},{**s,'ac_charge_enabled':False}):
            self.assertFalse(luna.decide(c,state,p,n)[0])
        q=joint.plan(c,p,n,20,1000)
        self.assertEqual(q['power_w'],1000)
        self.assertLessEqual(q['charges'][0]['battery_kwh'],1/6+1e-8)
    def test_gap_fails_closed_and_does_not_use_future_island(self):
        c,p,n,s=self.case();p.pop(8)
        self.assertIsNone(planning_end(p,n));self.assertIsNone(joint.plan(c,p,n,20))
        self.assertFalse(smart.plan(c,p,n,20)['windows']);self.assertTrue(dispatch.plan(c,p,n,20)['hold'])
    def test_known_horizon_not_unpublished_days(self):
        c,p,n,s=self.case();r=joint.plan(c,p[:4],n,20)
        self.assertEqual(datetime.fromisoformat(r['plan_end']),p[3]['end'])
        long=[dict(start=n,end=n+timedelta(days=4),ct=20)]
        self.assertEqual(planning_end(long,n),n+timedelta(hours=48))
    def test_daytime_solar_and_grid_share_charge_power(self):
        c,p,n,s=self.case(True);p=p[:20];p=[{**r,'ct':20 if i<4 else 50} for i,r in enumerate(p)]
        c.update(max_buy_ct_kwh=30,base_load_w=2000)
        c['_pv']={'rows':[dict(start=p[0]['start'],end=p[3]['end'],kw=3),dict(start=p[3]['end'],end=p[-1]['end'],kw=0)]}
        q=joint.plan(c,p,n,5,2000);eta=math.sqrt(.85)
        self.assertTrue(q['charges'])
        for t in q['trace']:
            a,b=datetime.fromisoformat(t['start']),datetime.fromisoformat(t['end']);h=(b-a).total_seconds()/3600
            solar=(1*eta*h) if a<p[3]['end'] else 0
            self.assertLessEqual(solar+t['grid_charge_kwh'],2*h+1e-7)
            expected=min(9,t['start_kwh']+solar)+t['grid_charge_kwh']-t['discharge_kwh']/eta
            self.assertAlmostEqual(t['end_kwh'],expected)
        for w in q['charges']:
            duration=(datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])).total_seconds()-130
            self.assertAlmostEqual(w['battery_kwh'],w['grid_power_w']/1000*duration/3600)
    def test_sufficient_solar_prevents_unneeded_grid_charge(self):
        c,p,n,s=self.case(True);p=p[:32]
        c['_pv']={'rows':[dict(start=p[0]['start'],end=p[-1]['end'],kw=3)]}
        q=joint.plan(c,p,n,20)
        self.assertEqual(q['planned_kwh'],0)
    def test_no_discharge_control_still_searches_daytime_candidates(self):
        c,p,n,s=self.case();c['smart_discharge_enabled']=False
        self.assertTrue(luna.decide(c,s,p,n)[0])
    def test_publication_retry_and_shared_revision(self):
        c,p,n,s=self.case();fetch=Mock(return_value=p[:44])
        with tempfile.TemporaryDirectory() as folder:
            get(c,folder,fetch,n);old=revision(folder)
            get(c,folder,fetch,n+timedelta(seconds=30));self.assertEqual(fetch.call_count,1)
            fetch.return_value=p
            get(c,folder,fetch,n+timedelta(seconds=61));self.assertEqual(fetch.call_count,2)
            self.assertNotEqual(revision(folder),old)
            get(c,folder,fetch,n+timedelta(minutes=3));self.assertEqual(fetch.call_count,2)
        self.assertEqual(poll_interval(c,n),60)
        self.assertEqual(poll_interval(c,n.replace(hour=18)),300)

class RollingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_controller_adopts_shared_prices_in_next_existing_loop(self):
        from types import SimpleNamespace
        from unittest.mock import patch,AsyncMock
        c,prices,now,state=RollingTests().case()
        c.update(mode='auto',expected_serial='TEST',password='fake')
        state['battery_power_w']=0
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return now
        fake=SimpleNamespace(device=SimpleNamespace(serial_number='TEST'),connect=AsyncMock(),
            snapshot=AsyncMock(return_value=state),login=AsyncMock(),charge=AsyncMock(),stop_charge=AsyncMock(),close=AsyncMock())
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);luna.write_json(folder/'commissioned.json',{'serial':'TEST'});luna.write_json(folder/'config.json',c)
            waits=0
            async def fast_wait(aw,timeout):
                nonlocal waits
                if getattr(getattr(aw,'cr_code',None),'co_name',None)=='wait':
                    waits+=1
                    if waits==1:
                        (folder/'tibber-prices.json').write_text('publication from web worker')
                        aw.close();raise TimeoutError()
                    aw.cr_frame.f_locals['self'].set()
                return await aw
            with patch('luna.Huawei',return_value=fake),patch('luna.datetime',Clock),patch('luna.time.monotonic',return_value=1000),patch('luna.asyncio.wait_for',side_effect=fast_wait),patch('luna.cached_prices',side_effect=[prices[:44],prices]) as fetch,patch('pv.refresh') as pv,patch('discharge.sync',new=AsyncMock()),patch('luna.emit') as emit:
                await luna.operate(SimpleNamespace(command='run',execute=True),c,folder)
            self.assertEqual(fetch.call_count,2);self.assertEqual(pv.call_count,1)
            self.assertEqual(fake.snapshot.await_count,3) # initial + one per existing loop
            decisions=[call.kwargs['eligible'] for call in emit.call_args_list if call.args[0]=='decision']
            self.assertEqual(decisions,[False,True]);fake.charge.assert_awaited_once();fake.stop_charge.assert_awaited_once()

    def test_web_worker_adopts_shared_publication_before_poll_deadline(self):
        from unittest.mock import patch
        from web import Dashboard
        c,prices,now,state=RollingTests().case()
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);app=Dashboard(folder,start_worker=False)
            app.closed=Mock();app.closed.is_set.side_effect=[False,False,True]
            app.closed.wait.side_effect=lambda seconds:(folder/'tibber-prices.json').write_text('new publication')
            with patch('web.time.monotonic',return_value=1000),patch('pv.refresh') as pv,patch('price_cache.get',side_effect=[(prices[:44],1,False),(prices,2,False)]) as fetch:
                app.price_worker()
            self.assertEqual(fetch.call_count,2);self.assertEqual(pv.call_count,1)
            self.assertEqual(app.price_data,prices)
