import tempfile
import unittest
from pathlib import Path
from car_planning import CarPlanning

class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=CarPlanning(Path(self.tmp.name))
        self.data={'revision':0,'profiles':{'born':{'name':'Born','consumption':18,'capacity':None,'reserve':20}},'trips':[{'id':'one','vehicle':'born','name':'Arbeit','km':80,'kind':'weekly','days':[0,2,4],'departure':'07:00','return':'17:00'}]}
    def test_roundtrip_and_revision(self):
        result=self.p.save(self.data);self.assertEqual(self.p.read(),result);self.assertEqual(result['revision'],1)
        self.assertTrue(result['trips'][0]['round_trip']);self.assertFalse(result['profiles']['born']['heat_pump'])
        with self.assertRaises(ValueError):self.p.save(self.data)
        self.assertEqual(self.p.path.stat().st_mode & 0o777,0o600)
    def test_invalid_and_no_partial_save(self):
        for key,value in [('days',[]),('km',float('nan')),('departure','27:00'),('vehicle','other')]:
            import copy
            d=copy.deepcopy(self.data);d['trips'][0][key]=value
            with self.assertRaises(ValueError):self.p.save(d)
        self.assertEqual(self.p.read()['revision'],0)
    def test_heat_pump_and_single_journey_persist(self):
        self.data['profiles']['born']['heat_pump']=True
        self.data['trips'][0]['round_trip']=False
        result=self.p.save(self.data)
        self.assertTrue(result['profiles']['born']['heat_pump'])
        self.assertFalse(result['trips'][0]['round_trip'])
    def test_once_overnight(self):
        t=self.data['trips'][0];t.update({'kind':'once','date':'2026-11-20','departure':'22:00','return':'06:00'})
        self.assertEqual(self.p.save(self.data)['trips'][0]['days'],[])

if __name__=='__main__':unittest.main()

class AdviceTests(unittest.TestCase):
    def setUp(self):
        from datetime import datetime,timezone
        self.now=datetime(2026,11,15,12,tzinfo=timezone.utc)
        self.plan={'profiles':{},'trips':[]};self.snapshot={'fetched_at':self.now.timestamp(),'devices':[]}
    def add(self,id,soc,km,departure='07:00',capacity=60):
        self.plan['profiles'][id]={'name':id,'consumption':20,'reserve':20,'capacity':capacity}
        self.plan['trips'].append({'id':id,'vehicle':id,'name':'Arbeit','kind':'weekly','days':[0],'km':km,'departure':departure,'return':'17:00'})
        self.snapshot['devices'].append({'device':{'id':id},'details':{'capabilities':[{'id':'storage.stateOfCharge','value':soc},{'id':'connector.status','value':'disconnected'}]}})
    def run_advice(self):
        from car_planning import advice
        from datetime import timedelta
        weather=[{'time':(self.now+timedelta(hours=h)).timestamp(),'c':20} for h in range(200)]
        return advice(self.plan,self.snapshot,now=self.now,context={'weather_at':self.now.timestamp(),'weather':weather})
    def test_first_uncovered_trip_priority(self):
        self.add('Born',25,100,'08:00');self.add('GTX',30,100,'07:00')
        r=self.run_advice();self.assertEqual(r['priority'],'GTX');self.assertEqual(r['vehicles'][1]['missing_kwh'],14);self.assertEqual(r['vehicles'][1]['target_soc'],54)
        self.assertTrue(any('Beide' in w for w in r['warnings']))
    def test_sufficient_and_missing_capacity(self):
        self.add('GTX',90,50);self.assertIsNone(self.run_advice()['priority'])
        self.plan['profiles']['GTX']['capacity']=None
        self.assertIn('Batteriekapazität',self.run_advice()['vehicles'][0]['message'])
    def test_stale_data_never_recommends(self):
        self.add('GTX',10,100);self.snapshot['fetched_at']-=1900
        self.assertIsNone(self.run_advice()['priority'])
    def test_known_old_measurement_never_recommends(self):
        self.add('GTX',10,100);self.snapshot['devices'][0]['details']['capabilities'][0]['updatedAt']='2026-11-14T12:00:00Z'
        self.assertIsNone(self.run_advice()['priority'])
    def test_multiple_trips_add_up(self):
        self.add('GTX',50,50)
        t=dict(self.plan['trips'][0],id='second',departure='18:00',km=50);self.plan['trips'].append(t)
        r=self.run_advice()['vehicles'][0];self.assertEqual(r['missing_kwh'],2);self.assertIn('18:00',r['deadline'])
