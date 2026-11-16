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

class HolidayTests(unittest.TestCase):
    def test_inclusive_dates_and_one_off_exceptions(self):
        from car_planning import trip_occurs
        from datetime import date
        plan={'holidays':[{'vehicle':'born','start':'2026-11-16','end':'2026-11-20'}]}
        weekly={'vehicle':'born','kind':'weekly','days':list(range(7))}
        for day,expected in [(15,True),(16,False),(18,False),(20,False),(21,True)]:
            self.assertEqual(trip_occurs(plan,weekly,date(2026,11,day)),expected)
        self.assertTrue(trip_occurs(plan,{'kind':'once','date':'2026-11-18'},date(2026,11,18)))

    def test_persistence_validation_and_legacy_save(self):
        with tempfile.TemporaryDirectory() as folder:
            store=CarPlanning(Path(folder))
            data=store.read();data['profiles']={'born':{'name':'Born'}};data['holidays']=[{'id':'h','vehicle':'born','name':'Ferien','start':'2026-11-16','end':'2026-11-20'}]
            saved=store.save(data);self.assertEqual(saved,store.read())
            saved.pop('holidays');saved=store.save(saved)
            self.assertEqual(len(saved['holidays']),1)
            saved['holidays'][0]['end']='2026-11-15'
            with self.assertRaises(ValueError):store.save(saved)
            self.assertEqual(store.read()['holidays'][0]['end'],'2026-11-20')
            data=store.read();data['profiles']={'born':{'name':'Born'}};data['holidays']=[]
            self.assertEqual(store.save(data)['holidays'],[])

    def test_both_vehicle_plans_and_estimates_exclude_routines(self):
        from car_planning import advice
        from datetime import datetime,timezone
        now=datetime(2026,11,15,12,tzinfo=timezone.utc)
        plan={'profiles':{},'trips':[],'holidays':[{'vehicle':v,'start':'2026-11-15','end':'2026-11-30'} for v in ['born','id3']]}
        devices=[]
        for vid in ['born','id3']:
            plan['profiles'][vid]={'name':vid,'consumption':18,'capacity':60,'reserve':20}
            plan['trips'].append({'id':vid,'vehicle':vid,'kind':'weekly','days':list(range(7)),'km':100,'departure':'08:00','return':'17:00'})
            devices.append({'device':{'id':vid},'details':{'capabilities':[{'id':'storage.stateOfCharge','value':30}]}})
        snapshot={'fetched_at':now.timestamp(),'devices':devices}
        result=advice(plan,snapshot,now=now)
        self.assertEqual(result['estimates'],[])
        self.assertEqual(result['rotation']['sessions'],[])
        self.assertIsNone(result['priority'])
        plan['trips'].append(dict(plan['trips'][0],id='special',kind='once',date='2026-11-17',km=150))
        result=advice(plan,snapshot,now=now)
        self.assertEqual([e['id'] for e in result['estimates']],['special'])
        self.assertEqual(result['priority'],'born')
        self.assertTrue(result['rotation']['sessions'])

    def test_holiday_only_pauses_selected_vehicle(self):
        from car_planning import trip_occurs
        from datetime import date
        plan={'holidays':[{'vehicle':'born','start':'2026-11-16','end':'2026-11-20'}]}
        trip={'vehicle':'born','kind':'weekly','days':[0]}
        day=date(2026,11,16)
        self.assertFalse(trip_occurs(plan,trip,day))
        self.assertTrue(trip_occurs(plan,dict(trip,vehicle='id3'),day))
        self.assertTrue(trip_occurs(plan,dict(trip,kind='once',date=day.isoformat()),day))

    def test_existing_shared_holidays_migrate_to_independent_copies(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            store=CarPlanning(Path(folder))
            store.path.write_text(json.dumps({'revision':1,'profiles':{'born':{},'id3':{}},'trips':[], 'holidays':[{'id':'old','name':'Ferien','start':'2026-12-01','end':'2026-12-10'}]}))
            data=store.read()
            self.assertEqual({h['vehicle'] for h in data['holidays']},{'born','id3'})
            self.assertEqual(len({h['id'] for h in data['holidays']}),2)
            data['holidays']=[h for h in data['holidays'] if h['vehicle']=='id3']
            store.save(data)
            self.assertEqual([h['vehicle'] for h in store.read()['holidays']],['id3'])
