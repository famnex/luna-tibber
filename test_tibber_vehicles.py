import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import Mock
from tibber_vehicles import VehicleProbe, REDIRECT

class VehicleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=VehicleProbe(Path(self.tmp.name))
    def test_state_session_and_secret_storage(self):
        self.p.begin({'client_id':'client','client_secret':'secret'},'session')
        url=REDIRECT+'?'+urlencode({'code':'code','state':self.p.pending['state']})
        with self.assertRaises(ValueError):self.p.finish({'callback_url':url},'other')
        with self.assertRaises(ValueError):self.p.finish({'callback_url':url.replace('localhost','evil.invalid')},'session')
        self.p.request=Mock(return_value={'access_token':'access','refresh_token':'refresh','expires_in':3600})
        result=self.p.finish({'callback_url':url},'session')
        self.assertTrue(result['connected']);self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(self.p.path.stat().st_mode & 0o777,0o600)
        self.assertIn('code_verifier',self.p.request.call_args.args[1])
        with self.assertRaises(ValueError):self.p.finish({'callback_url':url},'session')
    def test_read_and_cache_without_commands(self):
        self.p.token=Mock(return_value='access')
        self.p.request=Mock(side_effect=[{'homes':[{'id':'home'}]}, {'devices':[{'id':'car','name':'Born'}]}, {'soc':42,'timestamp':'2026-11-15T12:00:00Z'}])
        result=self.p.action('read',{},'session')
        self.assertEqual(result['devices'][0]['details']['soc'],42)
        self.assertEqual(self.p.action('read',{},'session'),result)
        self.assertEqual(self.p.request.call_count,3)
        for call in self.p.request.call_args_list:self.assertEqual(len(call.args),1)
    def test_refresh_rotates_and_disconnect(self):
        self.p.credentials={'refresh_token':'old','client_id':'client','client_secret':'secret','expires':0}
        self.p.request=Mock(return_value={'access_token':'access','refresh_token':'new','expires_in':3600})
        self.assertEqual(self.p.token(),'access')
        self.assertEqual(json.loads(self.p.path.read_text())['refresh_token'],'new')
        self.p.action('disconnect',{},'s');self.assertFalse(self.p.path.exists());self.assertFalse(self.p.status()['connected'])
    def test_unknown_format_is_error(self):
        with self.assertRaises(ValueError):self.p.rows({'oops':[]},'homes')

if __name__=='__main__':unittest.main()
