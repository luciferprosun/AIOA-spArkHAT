"""Doctor redaction and negative readiness, no actual tailnet interaction."""
import importlib
import importlib.util
import json
import unittest


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mobile_gateway.doctor'))
        self.doctor=importlib.import_module('runtime.mobile_gateway.doctor')

    def test_missing_peer_and_tls_is_blocked_not_pass(self):
        data=self.doctor.report()
        self.assertEqual('BLOCKED_EXTERNAL',data['readiness'])
        self.assertFalse(data['new_android_peer_confirmed']);self.assertFalse(data['host_tls_verified'])
        self.assertEqual('UNKNOWN',data['tailscale_status'])

    def test_identifiers_and_any_unknown_values_are_not_in_output(self):
        status={'BackendState':'Running','Self':{'Online':True,'DNSName':'private.example',
            'TailscaleIPs':['100.77.1.2'],'PublicKey':'nodekey:SECRET'},'Peer':{
            'peer-secret-id':{'OS':'android','Online':True,'HostName':'xiaomi-private','UserID':99}}}
        serve={'Web':{'private.example:443':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:4314'}}}}}
        data=self.doctor.report(status,serve,listening_ports={4314,18766})
        wire=json.dumps(data)
        for forbidden in ['private.example','100.77.1.2','nodekey','SECRET','peer-secret-id','xiaomi-private','UserID','Proxy']:
            self.assertNotIn(forbidden,wire)
        self.assertTrue(data['android_peer_observed']);self.assertTrue(data['serve_configuration_observed'])
        self.assertFalse(data['new_android_peer_confirmed']);self.assertEqual('BLOCKED_EXTERNAL',data['readiness'])

    def test_untrusted_truthy_fields_never_become_verified(self):
        for value in [None,[],{}, {'BackendState':'Running','Self':{'Online':'true'},'Peer':{'x':{'OS':'android','Online':1}}}]:
            data=self.doctor.report(value,{'tls_host_verified':True})
            self.assertFalse(data['new_android_peer_confirmed']);self.assertFalse(data['host_tls_verified'])
            self.assertEqual(0,data['tailscale_mutations'])


if __name__=='__main__':unittest.main()
