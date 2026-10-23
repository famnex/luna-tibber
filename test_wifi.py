import unittest
from unittest.mock import patch
import wifi

C = {'interface':'wlan0','uuid':'our-uuid','host':'192.168.200.1','ssid':'SUN2000-test'}
class WifiTests(unittest.TestCase):
    def nm(self, field, *args):
        return {'GENERAL.TYPE':'wifi','GENERAL.STATE':'30 (disconnected)',
                'GENERAL.CON-UUID':'--','UUID':'',
                'connection.interface-name':'wlan0','802-11-wireless.mode':'infrastructure',
                'ipv4.never-default':'yes','ipv4.ignore-auto-dns':'yes',
                'ipv4.ignore-auto-routes':'yes','ipv6.method':'disabled'}[field]
    def command(self,*args):
        return 'Not connected.' if args[0]=='iw' else '[]'
    def run_guard(self, nm=None, command=None):
        with patch('wifi.active',side_effect=lambda s:s=='NetworkManager'), patch('wifi.nm',side_effect=nm or self.nm), patch('wifi.command',side_effect=command or self.command):
            wifi.guard(C)
    def test_unused_adapter_accepted(self):
        self.run_guard()
    def test_foreign_connection_refused(self):
        with self.assertRaises(wifi.Conflict):
            self.run_guard(nm=lambda f,*a:'foreign' if f=='GENERAL.CON-UUID' else self.nm(f,*a))
    def test_non_nm_association_refused(self):
        with self.assertRaises(wifi.Conflict):
            self.run_guard(command=lambda *a:'Connected to aa:bb:cc:dd:ee:ff' if a[0]=='iw' else '[]')
    def test_default_route_refused(self):
        with self.assertRaises(wifi.Conflict):
            self.run_guard(command=lambda *a:'Not connected.' if a[0]=='iw' else '[{"dst":"default","dev":"wlan0"}]')
    def test_subnet_conflict_refused(self):
        with self.assertRaises(wifi.Conflict):
            self.run_guard(command=lambda *a:'Not connected.' if a[0]=='iw' else '[{"dst":"192.168.200.0/24","dev":"eth0"}]')
    def test_modified_profile_refused(self):
        with self.assertRaises(wifi.Conflict):
            self.run_guard(nm=lambda f,*a:'no' if f=='ipv4.never-default' else self.nm(f,*a))
    def test_keyfile_password_escaped(self):
        content=wifi.profile_text(C,'pass word\\123')
        self.assertIn('psk=pass\\sword\\\\123',content)
        self.assertIn('autoconnect=false',content)
        self.assertIn('never-default=true',content)
        with self.assertRaises(ValueError):
            wifi.profile_text(C,'pass\n[ipv4]')
    def test_conflict_never_activates(self):
        with patch('wifi.guard',side_effect=wifi.Conflict('busy')),patch('wifi.command') as cmd:
            with self.assertRaises(wifi.Conflict): wifi.connect(C)
            cmd.assert_not_called()
    def test_healthy_connection_not_restarted(self):
        with patch('wifi.guard'),patch('wifi.health',return_value=True),patch('wifi.command') as cmd:
            wifi.connect(C)
            cmd.assert_not_called()
    def test_watch_bounded_retries(self):
        with patch('wifi.connect',side_effect=RuntimeError('unavailable')) as conn,patch('wifi.time.sleep'):
            with self.assertRaises(RuntimeError):wifi.watch(C)
            self.assertEqual(conn.call_count,5)
    def test_watch_stops_on_conflict(self):
        with patch('wifi.connect',side_effect=wifi.Conflict('busy')) as conn,patch('wifi.time.sleep') as sleep:
            with self.assertRaises(wifi.Conflict):wifi.watch(C)
            self.assertEqual(conn.call_count,1)
            sleep.assert_not_called()
    def test_foreign_autoconnect_profile_refused(self):
        def values(field,*args):
            if field=='UUID': return 'foreign-profile'
            if field=='connection.type': return '802-11-wireless'
            if field=='connection.interface-name': return ''
            if field=='connection.autoconnect': return 'yes'
            return self.nm(field,*args)
        with self.assertRaises(wifi.Conflict): self.run_guard(nm=values)
    def test_dhcpcd_requires_reboot_after_exclusion(self):
        with patch('wifi.active',side_effect=lambda s:s in ('NetworkManager','dhcpcd')),patch('wifi.nm',side_effect=self.nm),patch('wifi.command',side_effect=self.command),patch('wifi.Path.read_text',side_effect=['denyinterfaces wlan0\n','boot-1']):
            with self.assertRaisesRegex(wifi.Conflict,'neu starten'):
                wifi.guard({**C,'dhcpcd_boot':'boot-1'})
