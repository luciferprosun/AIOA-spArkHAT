"""Reproduce the existing integration test as a redacted, zero-cost demo.

This is a test harness, not an Android emulator or a production server launcher.
All state/keys are temporary. It closes its own loopback:0 server before exit.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime.meta_hackathon.runtime_adapter import current_source
from test_meta_mobile_http import MobileHTTPTests


def main():
    test=MobileHTTPTests('test_http_enrollment_existing_core_run_receipt_stop_and_replay')
    test.fixture_source=current_source()
    try:
        test.setUp()
        test.test_http_enrollment_existing_core_run_receipt_stop_and_replay()
        print(json.dumps(test.evidence_summary,sort_keys=True,indent=2))
        return 0
    except Exception:
        print(json.dumps({'status':'UNKNOWN','verified':False,'automatic_retry':False}))
        return 1
    finally:
        test.tearDown()


if __name__=='__main__':raise SystemExit(main())
