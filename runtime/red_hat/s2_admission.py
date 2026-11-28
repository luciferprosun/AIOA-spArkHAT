"""Short-lived, challenge-bound off-guest admission for the S2 broker only."""

import hashlib
import secrets
import socket
from dataclasses import dataclass

from runtime.red_hat.authenticated_boundary import _open_seal
from runtime.red_hat.broker_protocol import digest, read_frame, require, send_frame
from runtime.red_hat.s2_continuity import boot_hash

WRITER_SCHEMA = "aioa.native.s2-writer-readback.v1"


@dataclass(frozen=True, slots=True)
class WriterAdmission:
    """A query-only management relay provisioned by the qualification supervisor."""

    channel: socket.socket
    spki_bytes: bytes

    def check(self, storage, binding):
        volume = storage.persistent
        require(volume is not None and binding.storage_digest == storage.digest
                and storage.exact_ref == binding.request.exact_ref
                and hashlib.sha256(self.spki_bytes).hexdigest() == volume.authority_spki_sha256
                and type(self.channel) is socket.socket and self.channel.family == socket.AF_UNIX, "NATIVE_S2_WRITER_PINS")
        query = {"schema": WRITER_SCHEMA, "storage_sha256": storage.digest, "volume_sha256": volume.volume_sha256,
                 "generation": volume.generation, "boot_sha256": boot_hash(), "exact_ref": storage.exact_ref,
                 "binding_sha256": digest(binding.to_wire()), "challenge": secrets.token_hex(32)}
        send_frame(self.channel, query, finish=False)
        payload = _open_seal(read_frame(self.channel, finished=False), self.spki_bytes.decode("ascii").strip(),
                             WRITER_SCHEMA)
        require(payload == query, "NATIVE_S2_WRITER_SCOPE")
