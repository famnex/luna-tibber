import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from notifications import Notifications,validate_subscription


def subscription(host='fcm.googleapis.com'):
    return {'endpoint':'https://'+host+'/test', 'keys':{'p256dh':base64.urlsafe_b64encode(b'\x04'+b'x'*64).decode().rstrip('='),'auth':base64.urlsafe_b64encode(b'x'*16).decode().rstrip('=')}}

class NotificationTests(unittest.TestCase):
    def test_endpoint_and_key_validation(self):
        validate_subscription(subscription())
        for host in ('127.0.0.1','localhost','web.push.apple.com.evil.test','fcm.googleapis.com@127.0.0.1'):
            with self.assertRaises(ValueError):validate_subscription(subscription(host))
        with self.assertRaises(ValueError):validate_subscription({'endpoint':'https://fcm.googleapis.com/test','keys':{}})
    def test_deduplication_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            n=Notifications(Path(tmp),start_worker=False)
            if not n.available:self.skipTest('Optionales Push-Paket fehlt')
            n.subscribe(subscription(),'mailto:test@example.org')
            self.assertTrue(n.emit('error','Fehler','Test','mailto:test@example.org'))
            self.assertFalse(n.emit('error','Fehler','Test','mailto:test@example.org'))
            other=Notifications(Path(tmp),start_worker=False)
            self.assertEqual(n.public_key,other.public_key)
            self.assertFalse(other.emit('error','Fehler','Test','mailto:test@example.org'))
            def send(**kwargs):n.closed.set();return SimpleNamespace(status_code=201)
            n.sender=Mock(side_effect=send);n.worker()
            n.sender.assert_called_once()
            n.unsubscribe(subscription()['endpoint'])
            self.assertFalse(n.emit('new','Neue Info','Test','mailto:test@example.org'))
    def test_real_encryption_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            n=Notifications(Path(tmp),start_worker=False)
            if not n.available:self.skipTest('Optionales Push-Paket fehlt')
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
            from requests import Response
            public=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
            sub=subscription();sub['keys']['p256dh']=base64.urlsafe_b64encode(public).decode().rstrip('=')
            n.subscribe(sub,'mailto:test@example.org');n.emit('test','Test','Private payload','mailto:test@example.org')
            def post(*args,**kwargs):
                self.assertNotIn(b'Private payload',kwargs['data'])
                self.assertIn('authorization',{k.lower() for k in kwargs['headers']})
                n.closed.set();response=Response();response.status_code=201;response._content=b'';return response
            n.session=SimpleNamespace(post=Mock(side_effect=post));n.worker()
            n.session.post.assert_called_once();self.assertEqual(n.error,'')
