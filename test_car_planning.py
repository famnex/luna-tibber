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
        with self.assertRaises(ValueError):self.p.save(self.data)
        self.assertEqual(self.p.path.stat().st_mode & 0o777,0o600)
    def test_invalid_and_no_partial_save(self):
        for key,value in [('days',[]),('km',float('nan')),('departure','27:00'),('vehicle','other')]:
            import copy
            d=copy.deepcopy(self.data);d['trips'][0][key]=value
            with self.assertRaises(ValueError):self.p.save(d)
        self.assertEqual(self.p.read()['revision'],0)
    def test_once_overnight(self):
        t=self.data['trips'][0];t.update({'kind':'once','date':'2026-11-20','departure':'22:00','return':'06:00'})
        self.assertEqual(self.p.save(self.data)['trips'][0]['days'],[])

if __name__=='__main__':unittest.main()
