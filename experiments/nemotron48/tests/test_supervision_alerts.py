"""No-network tests of emergency mail and supervised execution."""
from __future__ import annotations
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from experiments.nemotron48.alerts import alert_config_status,send_emergency_once
from experiments.nemotron48.audit import inspect_evidence
from experiments.nemotron48.policy import AdmissionError
from experiments.nemotron48.supervisor import SupervisorLimits, supervise
from experiments.nemotron48.storage import Store

URL="https://developer.mozilla.org/en-US/docs/Web/HTML"

class FakeMail:
    sent=0
    raise_on_send=False
    def __init__(self,*args,**kwargs):
        if args[:2]!=("smtp.gmail.com",465):
            raise AssertionError("unexpected SMTP destination")
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def login(self,user,password):
        if user!="sender@example.com" or password!="synthetic-test-credential":
            raise AssertionError("unexpected test credentials")
    def send_message(self,msg):
        if self.raise_on_send:raise TimeoutError("synthetic lost ack")
        type(self).sent+=1
        if "CRITICAL" not in msg["Subject"]:raise AssertionError("not critical")
        if "test@example.com" not in msg["To"]:raise AssertionError("wrong destination")
        return {}

class EmergencyTests(unittest.TestCase):
    def setUp(self):
        FakeMail.sent=0
        FakeMail.raise_on_send=False
        self.temp=tempfile.TemporaryDirectory(prefix="n48-mail-test-")
        self.dir=Path(self.temp.name)/"state"
        self.dir.mkdir(mode=0o700)
        self.env={
            "NEMOTRON48_NATALIA_CONSENT":"confirmed",
            "NEMOTRON48_ALERT_TO":"test@example.com",
            "NEMOTRON48_SMTP_USERNAME":"sender@example.com",
            "NEMOTRON48_SMTP_APP_PASSWORD":"synthetic-test-credential",
        }
    def tearDown(self):self.temp.cleanup()
    def test_consent_and_credential_gates(self):
        self.assertEqual(alert_config_status({})["reason"],"RECIPIENT_CONSENT_NOT_RECORDED")
        no_consent=dict(self.env)
        no_consent.pop("NEMOTRON48_NATALIA_CONSENT")
        with self.assertRaises(AdmissionError):
            send_emergency_once(self.dir,"n48test0001","MISSION_FATAL",
                                environ=no_consent,smtp_factory=FakeMail)
        no_password=dict(self.env)
        no_password.pop("NEMOTRON48_SMTP_APP_PASSWORD")
        self.assertFalse(alert_config_status(no_password)["ready"])
        self.assertEqual(FakeMail.sent,0)
    def test_single_email_no_duplicate(self):
        response=send_emergency_once(self.dir,"n48test0001","MISSION_FATAL",
                                     environ=self.env,smtp_factory=FakeMail)
        self.assertEqual(response["status"],"SMTP_ACCEPTED_DELIVERY_UNCONFIRMED")
        self.assertEqual(FakeMail.sent,1)
        with self.assertRaises(AdmissionError):
            send_emergency_once(self.dir,"n48test0001","MISSION_FATAL",
                                environ=self.env,smtp_factory=FakeMail)
        self.assertEqual(FakeMail.sent,1)
        marker=next(self.dir.glob("alert-*.json"))
        state=json.loads(marker.read_text())
        self.assertNotIn("test@example.com",marker.read_text())
        self.assertEqual(state["status"],"SMTP_ACCEPTED_DELIVERY_UNCONFIRMED")
    def test_uncertain_mail_must_not_retry(self):
        FakeMail.raise_on_send=True
        with self.assertRaises(AdmissionError):
            send_emergency_once(self.dir,"n48test0002","INTEGRITY_BROKEN",
                                environ=self.env,smtp_factory=FakeMail)
        FakeMail.raise_on_send=False
        with self.assertRaises(AdmissionError):
            send_emergency_once(self.dir,"n48test0002","INTEGRITY_BROKEN",
                                environ=self.env,smtp_factory=FakeMail)
        self.assertEqual(FakeMail.sent,0)
    def test_noncritical_code_rejected(self):
        with self.assertRaises(AdmissionError):
            send_emergency_once(self.dir,"n48test0003","NORMAL_UPDATE",
                                environ=self.env,smtp_factory=FakeMail)

class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="n48-supervise-test-")
        self.store=Store(Path(self.temp.name)/"state",create=True)
        self.store.initialize(owner="demo_owner",urls=[URL],hours=48,max_docs=25,max_depth=1)
    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
    def test_supervise_fixture_and_audit(self):
        with patch("experiments.nemotron48.mission.DocumentFetcher",
                   side_effect=AssertionError("network must not be used")):
            result=supervise(self.store,limits=SupervisorLimits(max_wall_seconds=10,
                                max_segments=20,items_per_segment=1))
        self.assertIn(result["supervisor"]["terminal"],
                      {"DONE_EARLY_NOT_48H","NO_PENDING_WORK_NOT_48H"})
        self.assertGreaterEqual(result["supervisor"]["segments"],1)
        self.assertEqual(result["supervisor"]["run_48h_certified"],False)
        review=inspect_evidence(self.store)
        self.assertEqual(review["verdict"],"NOT_PROVEN_48H")
        self.assertFalse(review["checks"]["model_calls"])
        self.assertFalse(review["checks"]["active_duration_48h"])
    def test_live_cannot_start_without_alert_setup(self):
        with patch("experiments.nemotron48.supervisor.alert_config_status",
                   return_value={"ready":False,"reason":"NOT_CONFIGURED"}):
            with self.assertRaises(AdmissionError):
                supervise(self.store,live_network=True,authorized_network=True,
                          limits=SupervisorLimits(max_wall_seconds=4,max_segments=1))

if __name__=="__main__":unittest.main()
