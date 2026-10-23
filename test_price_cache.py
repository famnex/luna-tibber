import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock
from price_cache import get

class CacheTests(unittest.TestCase):
    def test_shared_restart_fallback_expiry_and_account(self):
        now=datetime(2026,10,24,tzinfo=timezone.utc)
        c={'tibber_token':'test','tibber_home_id':'home'}
        rows=[{'start':now,'end':now+timedelta(hours=36),'ct':20}]
        fetch=Mock(return_value=rows)
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(get(c,folder,fetch,now)[2])
            get(c,folder,fetch,now+timedelta(seconds=60))
            self.assertEqual(fetch.call_count,1)
            fetch.side_effect=OSError('offline')
            self.assertTrue(get(c,folder,fetch,now+timedelta(minutes=6))[2])
            with self.assertRaises(OSError):get(c,folder,fetch,now+timedelta(hours=25))
            with self.assertRaises(OSError):get({**c,'tibber_home_id':'other'},folder,fetch,now)
    def test_expired_intervals_not_reused(self):
        now=datetime(2026,10,24,tzinfo=timezone.utc)
        c={'tibber_token':'test','tibber_home_id':'home'}
        fetch=Mock(return_value=[{'start':now,'end':now+timedelta(minutes=15),'ct':-2}])
        with tempfile.TemporaryDirectory() as folder:
            get(c,folder,fetch,now)
            fetch.side_effect=OSError()
            with self.assertRaises(OSError):get(c,folder,fetch,now+timedelta(minutes=16))
