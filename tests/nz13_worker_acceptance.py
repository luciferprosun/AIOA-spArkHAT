"""Offline candidate-message -> real Core/Linux -> local Git acceptance.

This transport is a deterministic test fixture. Its token usage is synthetic;
no real provider, host credentials, process launcher or network is involved.
The existing kernel acceptance owns every effect, warrant, capsule and oracle.
"""

import json
import sys
from pathlib import Path

import nz11_kernel_acceptance as kernel

from runtime.mission.worker import SyntheticWorker


class WireFixtureWorker(SyntheticWorker):
    """Exercise inert wire admission through the established WorkerPort lifecycle."""

    def __init__(self, candidates, *, clock):
        super().__init__(candidates, model_id="nz13-wire-fixture", clock=clock)
        self.messages = 0

    def poll(self, session):
        with self._lock:
            box = self._mailbox(session)
            if self._pending and box.result(session) is None:
                self._pending = False
                try:
                    candidate = next(self._candidates)
                except StopIteration:
                    box.fail(session, "WORKER_CRASH")
                else:
                    raw = json.dumps({
                        "schema": "aioa.worker-candidate.v1",
                        "task_id": box.task.task_id,
                        "run_id": box.task.run_id,
                        "session_id": session.session_id,
                        "task_digest": box.task.digest,
                        "files": [{"path": f.path, "text": f.text}
                                  for f in candidate.files],
                    }, separators=(",", ":")).encode()
                    box.complete_json(session, raw, completion_tokens=64)
                    self.messages += 1
            return box.drain(session)


def main(manifest, output):
    workers = []

    def factory(candidates, *, clock):
        worker = WireFixtureWorker(candidates, clock=clock)
        workers.append(worker)
        return worker

    kernel.main(manifest, output, worker_factory=factory)
    assert len(workers) == 1 and workers[0].messages == 2
    proof = {
        "schema": "aioa.nz13.worker-wire-acceptance.v1",
        "status": "PASS_OFFLINE_FIXTURE_ONLY",
        "transport": "EXPLICIT_SYNTHETIC_CANDIDATE_MESSAGES",
        "real_model_certification": "NOT_CERTIFIED",
        "real_model_test": "MODEL_TEST_BLOCKED_OWNER",
        "messages": workers[0].messages,
        "repair": ["FAIL", "PASS"],
        "effects": "EXISTING_CORE_LINUX_BROKER_AND_LOCAL_DISPOSABLE_BARE_GIT",
        "github_write": False,
        "paid_calls": 0,
    }
    with (output / "NZ13_WORKER_WIRE_ACCEPTANCE.json").open("x") as stream:
        json.dump(proof, stream, indent=2)
    print(json.dumps(proof), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
