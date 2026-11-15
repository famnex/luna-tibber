import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from car_context import CarContext,estimate_trip,cheap_night
from car_planning import advice

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,15,12,tzinfo=timezone.utc)
        self.p={'consumption':20,'capacity':60,'reserve':20}
        self.t={'km':20,'return':'17:00','round_trip':True}
    def weather(self,c):
        return {'weather_at':self.now.timestamp(),'weather':[{'time':(self.now+timedelta(hours=h)).timestamp(),'c':c} for h in range(200)]}
    def prices(self,price=20):
        rows=[]
        for d in range(-4,2):
            start=self.now.replace(hour=0)+timedelta(days=d)
            for h in range(24):
                a=start+timedelta(hours=h);b=a+timedelta(hours=1)
                rows.append({'start':a.isoformat(),'end':b.isoformat(),'ct':40 if a<self.now else price})
        return {'prices':rows}
    def test_heatpump_and_short_trip(self):
        cold=estimate_trip(self.t,self.p,self.now,self.weather(0),self.now)['kwh']
        pump=estimate_trip(self.t,dict(self.p,heat_pump=True),self.now,self.weather(0),self.now)['kwh']
        mild=estimate_trip(self.t,self.p,self.now,self.weather(20),self.now)['kwh']
        self.assertGreater(cold,pump);self.assertGreater(pump,mild);self.assertEqual(mild,4)
        single=estimate_trip(dict(self.t,round_trip=False),self.p,self.now,self.weather(0),self.now)['kwh']
        self.assertGreater(cold,single)
    def test_fallback_and_overnight(self):
        t={**self.t,'return':'06:00'};r=estimate_trip(t,self.p,self.now,{},self.now)
        self.assertEqual(r['legs'],2);self.assertEqual(r['source'],'Saisonannahme');self.assertGreater(r['kwh'],4)
        stale=self.weather(20);stale['weather_at']-=22000
        self.assertEqual(estimate_trip(t,self.p,self.now,stale,self.now)['source'],'Saisonannahme')
    def test_cheap_night_evidence(self):
        r=cheap_night(self.prices(),'Europe/Berlin',self.now)
        self.assertTrue(r['qualified']);self.assertEqual(r['ct'],20);self.assertEqual(r['reference_ct'],40)
        self.assertFalse(cheap_night(self.prices(35),'Europe/Berlin',self.now)['qualified'])
        self.assertFalse(cheap_night({},'Europe/Berlin',self.now)['qualified'])
    def test_gaps_and_price_spike_not_cheap_window(self):
        c=self.prices(40)
        # One low hour cannot qualify a 2h window with enough reduction here.
        future=[r for r in c['prices'] if r['start']>self.now.isoformat()]
        future[12]['ct']=30
        self.assertFalse(cheap_night(c,'Europe/Berlin',self.now)['qualified'])
        c['prices']=[r for r in c['prices'] if datetime.fromisoformat(r['start']).hour%2==0]
        self.assertFalse(cheap_night(c,'Europe/Berlin',self.now)['qualified'])
    def test_cache_account_location_and_persistence(self):
        with tempfile.TemporaryDirectory() as f:
            c={'tibber_token':'private','tibber_home_id':'a'};cache=CarContext(Path(f))
            rows=[dict(r,start=datetime.fromisoformat(r['start']),end=datetime.fromisoformat(r['end'])) for r in self.prices()['prices']]
            cache.refresh(c,rows,self.now)
            self.assertTrue(CarContext(Path(f)).snapshot(c)['prices'])
            self.assertEqual(cache.snapshot(dict(c,tibber_home_id='other'))['prices'],[])
            self.assertNotIn('private',cache.path.read_text());self.assertEqual(cache.path.stat().st_mode&0o777,0o600)
    def test_stock_full_for_week_and_one_car(self):
        plan={'profiles':{'a':self.p,'b':self.p},'trips':[]};snapshot={'fetched_at':self.now.timestamp(),'devices':[]}
        for vid in ('a','b'):
            plan['trips'].append(dict(self.t,id=vid,vehicle=vid,kind='weekly',days=[0,1,2,3,4],departure='07:00',km=70))
            snapshot['devices'].append({'device':{'id':vid},'details':{'capabilities':[{'id':'storage.stateOfCharge','value':30},{'id':'connector.status','value':'connected' if vid=='a' else 'disconnected'}]}})
        c={**self.prices(),**self.weather(20)};r=advice(plan,snapshot,now=self.now,context=c)
        self.assertEqual(r['priority_kind'],'stock');self.assertEqual(r['priority'],'a')
        self.assertEqual(r['vehicles'][0]['opportunity']['target_soc'],100)
        # A small weekly need must not force a full battery.
        for t in plan['trips']:t['days']=[0];t['km']=20
        r=advice(plan,snapshot,now=self.now,context=c)
        self.assertNotIn('priority_kind',r)
    def test_urgent_trip_not_delayed_to_night(self):
        plan={'profiles':{'a':self.p},'trips':[dict(self.t,id='a',vehicle='a',kind='once',date='2026-11-15',departure='14:00',km=100)]}
        snapshot={'fetched_at':self.now.timestamp(),'devices':[{'device':{'id':'a'},'details':{'capabilities':[{'id':'storage.stateOfCharge','value':20}]}}]}
        r=advice(plan,snapshot,now=self.now,context={**self.prices(),**self.weather(20)})
        self.assertEqual(r['priority'],'a');self.assertNotIn('opportunity',r['vehicles'][0])

if __name__=='__main__':unittest.main()
