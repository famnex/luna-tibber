import unittest
from datetime import datetime,timezone,timedelta
from car_rotation import coordinate
from car_notifications import alerts

class RotationTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,15,12,tzinfo=timezone.utc)
        self.plan={'profiles':{v:{'capacity':60,'reserve':20,'consumption':20} for v in ('a','b')},'trips':[]}
        self.cars=[{'id':'a','name':'ID.3','soc':40,'connected':False},{'id':'b','name':'Born','soc':65,'connected':True}]
        self.context={'weather_at':self.now.timestamp(),'weather':[{'time':(self.now+timedelta(hours=h)).timestamp(),'c':20} for h in range(240)]}
    def trip(self,car,day,km,departure='07:00',home='17:00'):
        self.plan['trips'].append({'id':car+day,'vehicle':car,'kind':'once','date':day,'km':km,'departure':departure,'return':home})
    def run_plan(self):return coordinate(self.plan,self.cars,'Europe/Berlin',self.now,self.context)
    def test_cover_more_than_tomorrow_for_other_car(self):
        # A needs 20 kWh Monday and another 20 Tuesday. B needs its own Monday night.
        self.trip('a','2026-11-16',100);self.trip('a','2026-11-17',100)
        self.trip('b','2026-11-16',50);self.trip('b','2026-11-17',100)
        r=self.run_plan();self.assertEqual(r['status'],'planned');s=r['sessions']
        self.assertEqual(s[0]['id'],'a');self.assertGreaterEqual(s[0]['target_soc'],87)
        self.assertEqual(s[1]['id'],'b');self.assertTrue(s[0]['other_next_night'])
        self.assertEqual(len({x['start'] for x in s}),len(s))
        self.assertGreater(s[0]['kwh'],20)
    def test_conflict_both_empty_before_same_morning(self):
        self.cars[1]['soc']=30
        for car in ('a','b'):self.trip(car,'2026-11-16',100)
        r=self.run_plan();self.assertEqual(r['status'],'conflict');self.assertEqual(r['sessions'],[])
    def test_absent_car_not_assigned_overnight(self):
        self.trip('a','2026-11-16',100,departure='23:00',home='07:00')
        r=self.run_plan();self.assertEqual(r['status'],'planned')
        self.assertFalse(any(x['id']=='a' and x['start'].startswith('2026-11-16') for x in r['sessions']))
    def test_sufficient_energy_and_missing_soc(self):
        self.trip('a','2026-11-16',10)
        self.assertEqual(self.run_plan()['sessions'],[])
        del self.cars[1]['soc'];self.assertEqual(self.run_plan()['status'],'missing')
    def test_three_day_bridge(self):
        self.cars[1]['soc']=35
        for day in ('2026-11-16','2026-11-17','2026-11-18'):self.trip('a',day,70)
        self.trip('b','2026-11-17',150)
        r=self.run_plan();self.assertEqual(r['status'],'planned')
        first=r['sessions'][0];self.assertEqual(first['id'],'a');self.assertGreaterEqual(first['target_soc'],90)
    def test_notification_only_next_car_and_short(self):
        car={'id':'a','name':'ID.3','soc':40,'connected':False,'connector_status':'disconnected','rotation':{'start':'2026-11-15T22:00:00+01:00','target_soc':87,'kwh':28.2,'add_soc':47}}
        d={'priority':'a','priority_kind':'rotation','rotation':{'status':'planned'},'vehicles':[car,{'id':'b','name':'Cupra Born','connected':False,'connector_status':'disconnected'}]}
        r=alerts(d,self.now);self.assertEqual(len(r),1);self.assertIn('Kein Auto ist angesteckt.',r[0]['body']);self.assertIn('diese Nacht',r[0]['body']);self.assertIn('47 Prozentpunkte',r[0]['body']);self.assertLess(len(r[0]['body']),230)
        d['vehicles'][1]['connected']=True;self.assertIn('Cupra Born ist angesteckt, aber ID.3',alerts(d,self.now)[0]['body'])

    def test_connected_car_notification_requires_only_evcc_planning(self):
        car={'id':'b','name':'Born','soc':34,'capacity':55,'connected':True,'connector_status':'connected','rotation':{'start':'2026-11-15T22:00:00+01:00','target_soc':92,'kwh':31.9,'add_soc':58}}
        advice={'priority':'b','priority_kind':'rotation','rotation':{'status':'planned'},'vehicles':[car]}
        body=alerts(advice,self.now)[0]['body']
        self.assertIn('58 Prozentpunkte (31,9 kWh)',body)
        self.assertIn('Bereits angeschlossen – kein Umstecken nötig.',body)
        self.assertIn('in evcc einplanen, falls noch nicht geschehen',body)
        self.assertNotIn('Bitte umstecken',body)
        car['connector_status']='unknown';car['connected']=False
        self.assertIn('Anschlussstatus unbekannt',alerts(advice,self.now)[0]['body'])

    def test_charging_suppresses_urgent_reminder_and_morning_waits(self):
        car={'id':'a','name':'Born','soc':95,'connected':True,'connector_status':'connected','charging_status':'charging','rotation':{'start':'2026-11-16T00:00:00+01:00','end':'2026-11-16T06:00:00+01:00','target_soc':97,'kwh':1.1,'add_soc':2}}
        d={'priority':'a','priority_kind':'rotation','rotation':{'status':'planned'},'vehicles':[car]}
        self.assertEqual(alerts(d,datetime.fromisoformat('2026-11-16T00:00:00+01:00')),[])
        car['charging_status']='idle';car['rotation']['start']='2026-11-16T22:00:00+01:00';car['rotation']['end']='2026-11-17T06:00:00+01:00'
        self.assertEqual(alerts(d,datetime.fromisoformat('2026-11-16T06:00:00+01:00')),[])
        car['rotation'].update(expected_start_soc=49.3,projected_before_kwh=25.1,kwh=26.22,add_soc=47.7)
        message=alerts(d,datetime.fromisoformat('2026-11-16T18:00:00+01:00'))[0]['body']
        self.assertIn('Nach den geplanten Fahrten',message)
        self.assertIn('49,3 % → 97 %',message)

    def test_rotation_exposes_future_start_instead_of_current_gap(self):
        self.now=datetime.fromisoformat('2026-11-16T06:30:00+01:00')
        self.cars[0]['soc']=95
        for day in ('2026-11-16','2026-11-17','2026-11-18'):self.trip('a',day,100)
        result=self.run_plan();self.assertEqual(result['status'],'planned')
        slot=result['sessions'][0]
        self.assertEqual(slot['current_soc'],95)
        self.assertLess(slot['expected_start_soc'],95)
        self.assertAlmostEqual(slot['kwh'],(slot['target_soc']-slot['expected_start_soc'])*.6,delta=.04)
