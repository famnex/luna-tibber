import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,date,timezone
from unittest.mock import patch
from forecast import *
from car_energy import optimise,pv_surplus
from car_notifications import alerts

class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.now=datetime(2026,11,19,8,tzinfo=UTC)
        self.c={'tibber_token':'secret','tibber_home_id':'home','timezone':'Europe/Berlin',**DEFAULTS}
    def tearDown(self):self.tmp.cleanup()
    def row(self,a,ct=30,energy=10):return {'start':a,'end':a+timedelta(minutes=15),'ct':ct,'energy_ct':energy}
    def test_addon_gross_idempotent_and_account_bound(self):
        rows=[self.row(self.now)]
        learn(self.c,self.folder,rows,self.now);learn(self.c,self.folder,rows,self.now)
        data=json.loads((self.folder/'price-addons.json').read_text());slot=data['profile']['weekday']['09:00']
        self.assertAlmostEqual(slot['ct'],18.1)
        self.assertEqual(len(data['profile']['weekday']),1)
        learn({**self.c,'tibber_home_id':'other'},self.folder,[],self.now)
        self.assertEqual(json.loads((self.folder/'price-addons.json').read_text())['profile'],{})
    def test_full_historical_day_fills_weekend_and_refreshes(self):
        start=datetime(2026,11,18,23,tzinfo=UTC)
        rows=[self.row(start+timedelta(minutes=i*15),30+i/100) for i in range(96)]
        learn(self.c,self.folder,rows,self.now)
        profile=json.loads((self.folder/'price-addons.json').read_text())['profile']
        self.assertEqual(len(profile['latest']),96)
        a=datetime(2026,11,21,8,tzinfo=UTC)
        pred=[{'start':a,'end':a+timedelta(minutes=15),'wholesale_ct':10}]
        out=merge(self.c,[],pred,profile,self.now)
        self.assertTrue(out[0]['addon_fallback']);self.assertAlmostEqual(out[0]['ct'],30.36)
        # Partial newer data must not destroy the complete fallback day.
        learn(self.c,self.folder,[self.row(start+timedelta(days=1),90)],self.now)
        profile=json.loads((self.folder/'price-addons.json').read_text())['profile']
        self.assertEqual(len(profile['latest']),96)
        learn(self.c,self.folder,[self.row(start+timedelta(days=1,minutes=i*15),40) for i in range(96)],self.now)
        profile=json.loads((self.folder/'price-addons.json').read_text())['profile']
        self.assertAlmostEqual(merge(self.c,[],pred,profile,self.now)[0]['ct'],40)
        learn(self.c,self.folder,[self.row(a,45)],self.now)
        profile=json.loads((self.folder/'price-addons.json').read_text())['profile']
        self.assertFalse(merge(self.c,[],pred,profile,self.now)[0]['addon_fallback'])

    def test_holidays_and_weekends(self):
        self.assertEqual(day_type(date(2026,12,25),'HE'),'weekend')
        self.assertEqual(day_type(date(2026,11,21),'HE'),'weekend')
        self.assertEqual(day_type(date(2026,6,4),'HE'),'weekend')
        self.assertEqual(day_type(date(2026,6,4),'BE'),'weekday')
    def test_no_profile_fabrication_and_exact_wins(self):
        p={'start':self.now,'end':self.now+timedelta(minutes=15),'wholesale_ct':-10}
        self.assertEqual(merge(self.c,[],[p],{},self.now),[])
        profile={'weekday':{'09:00':{'ct':18.1,'observed':self.now.isoformat()}}}
        self.assertAlmostEqual(merge(self.c,[],[p],profile,self.now)[0]['ct'],6.2)
        self.assertEqual(merge(self.c,[self.row(self.now)],[p],profile,self.now)[0]['ct'],30)
        self.assertEqual(merge(self.c,[],[p],profile,self.now+timedelta(days=40)),[])
    def test_parse_units_invalid_and_cache_error_redaction(self):
        payload={'data':[{'start':self.now.isoformat(),'end':(self.now+timedelta(minutes=15)).isoformat(),'price_ct_kwh':-5,'total_ct_kwh':999}]}
        self.assertEqual(parse(payload,self.now)[0]['wholesale_ct'],-5)
        payload['data'][0]['end']=self.now.isoformat()
        with self.assertRaises(ValueError):parse(payload,self.now)
        f=Forecast(self.folder)
        with patch('forecast.urlopen',side_effect=RuntimeError('https://url?token=secret')) as call:
            f.refresh({**self.c,'energyforecast_api_key':'secret'},self.now);f.refresh({**self.c,'energyforecast_api_key':'secret'},self.now)
            self.assertEqual(call.call_count,1);self.assertNotIn('secret',f.error)
    def test_window_requires_complete_coverage(self):
        rows=[self.row(self.now),self.row(self.now+timedelta(minutes=30))]
        self.assertIsNone(average(rows,self.now,self.now+timedelta(minutes=45)))
        self.assertEqual(average(rows,self.now,self.now+timedelta(minutes=15)),30)
    def test_tibber_components_are_converted_to_cents(self):
        import luna
        from unittest.mock import MagicMock
        payload={'data':{'viewer':{'homes':[{'id':'home','currentSubscription':{'priceInfo':{'today':[{'startsAt':self.now.isoformat(),'currency':'EUR','total':.30,'energy':.10,'tax':.20}],'tomorrow':[]}}}]}}}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(payload)
        with patch('luna.urlopen',return_value=response):rows=luna.fetch_prices(self.c)
        self.assertEqual(rows[0]['energy_ct'],10);self.assertEqual(rows[0]['tax_ct'],20)
        self.assertEqual(rows[0]['ct'],30)

    def test_forecast_response_cache_and_key_is_not_exposed(self):
        from unittest.mock import MagicMock
        payload={'generated_at':self.now.isoformat(),'data':[{'start':self.now.isoformat(),'end':(self.now+timedelta(minutes=15)).isoformat(),'price_ct_kwh':10}]}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(payload)
        c={**self.c,'energyforecast_api_key':'private-value'};f=Forecast(self.folder)
        learn(c,self.folder,[self.row(self.now)],self.now)
        with patch('forecast.urlopen',return_value=response) as request:
            f.refresh(c,self.now);f.refresh(c,self.now+timedelta(hours=1));self.assertEqual(request.call_count,1)
        d=f.snapshot(c,[],self.now)
        self.assertEqual(d['prices'][0]['source'],'forecast')
        self.assertNotIn('private-value',json.dumps(d,default=str))
        self.assertIsNone(f.cached({**c,'energyforecast_api_key':'another'},self.now))
        self.assertIsNone(f.cached(c,self.now+timedelta(hours=25)))

    def test_dst_repeated_slot_has_local_profile(self):
        a=datetime(2026,10,25,0,tzinfo=UTC);b=a+timedelta(hours=1)
        learn(self.c,self.folder,[self.row(a,30),self.row(b,31)],a)
        d=json.loads((self.folder/'price-addons.json').read_text())['profile']
        self.assertEqual(len(d['weekend']),1);self.assertAlmostEqual(d['weekend']['02:00']['ct'],19.1)

class EnergyTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,19,8,tzinfo=UTC)
        self.plan={'profiles':{v:{'capacity':60,'reserve':20,'consumption':20} for v in ['a','b']},'trips':[]}
        self.vehicles=[{'id':'a','name':'ID.3','soc':30,'capacity':60,'connected':False,'connector_status':'disconnected'},{'id':'b','name':'Born','soc':70,'capacity':60,'connected':False}]
        self.slot={'id':'a','name':'ID.3','start':'2026-11-21T22:00:00+01:00','end':'2026-11-22T06:00:00+01:00','kwh':20,'covers_until':'2026-11-25T06:00:00+01:00','target_soc':64,'expected_start_soc':30}
        self.baseline={'status':'planned','sessions':[self.slot]}
        self.prices=[]
        for i in range(96*5):
            a=self.now+timedelta(minutes=15*i)
            self.prices.append({'start':a,'end':a+timedelta(minutes=15),'ct':10 if a.date()==date(2026,11,20) else 50,'source':'forecast'})
        self.context={'forecast_prices':self.prices,'energy_settings':DEFAULTS}
    def test_advance_to_cheaper_day(self):
        out=optimise(self.plan,self.vehicles,self.baseline,'Europe/Berlin',self.now,self.context)
        self.assertIn('advanced_from',out['sessions'][0]);self.assertLess(instant(out['sessions'][0]['start']),instant(self.slot['start']))
        self.assertGreater(out['sessions'][0]['saving_eur'],0)
        self.assertEqual(out['sessions'][0]['source'],'grid')
    def test_capacity_and_missing_prices_do_not_invent_schedule(self):
        self.vehicles[0]['soc']=95
        self.assertEqual(optimise(self.plan,self.vehicles,self.baseline,'Europe/Berlin',self.now,self.context)['sessions'],self.baseline['sessions'])
        self.context['forecast_prices']=[];self.vehicles[0]['soc']=30
        out=optimise(self.plan,self.vehicles,self.baseline,'Europe/Berlin',self.now,self.context)
        self.assertNotIn('advanced_from',out['sessions'][0])
    def test_away_cheapest_day_not_used(self):
        self.plan['trips']=[{'id':'trip','vehicle':'a','kind':'once','date':'2026-11-20','departure':'00:00','return':'23:59','km':1}]
        out=optimise(self.plan,self.vehicles,self.baseline,'Europe/Berlin',self.now,self.context)
        s=out['sessions'][0]
        self.assertFalse(instant(s['start'])<datetime(2026,11,20,22,59,tzinfo=UTC) and instant(s['end'])>datetime(2026,11,19,23,tzinfo=UTC))
    def test_pv_only_after_house_full_and_no_stale_measurement(self):
        c={'battery_capacity_kwh':10,'battery_floor_soc':10,'base_load_w':1000,'battery_idle_w':0,'roundtrip_efficiency':1,**DEFAULTS}
        rows=[{'start':self.now,'end':self.now+timedelta(hours=5),'kw':5}]
        sample={'time':self.now.isoformat(),'soc':50}
        result=pv_surplus(c,rows,sample,self.now)
        self.assertEqual(result[0]['full_at'],self.now+timedelta(hours=1.25))
        self.assertAlmostEqual(sum(r['kw']*(r['end']-r['start']).total_seconds()/3600 for r in result),15)
        self.assertEqual(pv_surplus(c,rows,{**sample,'time':(self.now-timedelta(hours=2)).isoformat()},self.now),[])
    def test_pv_split_not_double_allocated(self):
        a=self.now+timedelta(hours=3);b=a+timedelta(hours=2)
        self.context['pv_surplus']=[{'start':a,'end':b,'kw':4,'full_at':a}]
        out=optimise(self.plan,self.vehicles,self.baseline,'Europe/Berlin',self.now,self.context)
        solar=[s for s in out['sessions'] if s.get('source')=='pv']
        self.assertEqual(len(solar),1);self.assertAlmostEqual(solar[0]['kwh'],7.2)
        self.assertAlmostEqual(sum(s['kwh'] for s in out['sessions']),20)
    def test_two_cars_do_not_share_a_night(self):
        second={**self.slot,'id':'b','name':'Born','kwh':12,'start':'2026-11-22T22:00:00+01:00','end':'2026-11-23T06:00:00+01:00'}
        self.baseline['sessions'].append(second)
        out=optimise(self.plan,self.vehicles,self.baseline,'Europe/Berlin',self.now,self.context)
        nights={}
        for s in out['sessions']:
            a=instant(s['start']).astimezone(ZoneInfo('Europe/Berlin'))
            if 6<=a.hour<22:continue
            key=(a-timedelta(days=1) if a.hour<6 else a).date()
            self.assertNotIn(key,nights);nights[key]=s['id']
        self.assertEqual(len(out['sessions']),2)

    def test_unreachable_charge_duration_is_not_certified(self):
        self.context['energy_settings']={**DEFAULTS,'car_charge_kw':1}
        out=optimise(self.plan,self.vehicles,self.baseline,'Europe/Berlin',self.now,self.context)
        self.assertIn('nicht bestätigen',out['message'])
        self.assertNotIn('advanced_from',out['sessions'][0])

    def test_pv_stops_at_forecast_gap(self):
        c={'battery_capacity_kwh':10,'battery_floor_soc':10,'base_load_w':1000,'battery_idle_w':0,'roundtrip_efficiency':1,**DEFAULTS}
        rows=[{'start':self.now+timedelta(hours=1),'end':self.now+timedelta(hours=3),'kw':5}]
        self.assertEqual(pv_surplus(c,rows,{'time':self.now.isoformat(),'soc':100},self.now),[])

    def test_morning_only_disconnected_and_daytime(self):
        p={'id':'a','name':'ID.3','start':(self.now+timedelta(hours=3)).isoformat(),'end':(self.now+timedelta(hours=5)).isoformat(),'kwh':7.2}
        d={'vehicles':self.vehicles,'pv_opportunity':p}
        self.assertEqual(len(alerts(d,self.now,morning_time='08:00')),1)
        self.assertEqual(alerts(d,self.now,morning_time='10:00'),[])
        self.vehicles[0]['connected']=True
        self.assertEqual(alerts(d,self.now),[])

if __name__=='__main__':unittest.main()
