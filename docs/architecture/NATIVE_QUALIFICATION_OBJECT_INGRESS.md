# Native qualification object ingress

The existing explicit Native qualification port sends the deterministic plan's
objects to the enrolled broker after Core persists START and acknowledges
its original warrant. Core's signature covers the immutable authorization
binding and the SHA-256 digest and byte count of the object batch. The broker
checks socket credentials, the signature, the original target pins, and
enrollment before reading the separately bounded batch on that connection.
Other protocol paths still require end of stream directly after their frame.

The broker checks the Git SHA-1 of each object, the authorized commit OID,
the closure of the commit's tree, entry modes, and the absence of extra
objects. The commit's existing parent belongs to the previously prepared
repository. SHA-256 authenticates the exact transferred bytes. The fixture
importer has no shell, path input, or arbitrary Git command. It creates
loose objects under the validated objects directory, checks existing bytes
and fsyncs accepted objects and directory entries. Any uncertain import
leaves the consumed attempt fence in place.

Object preparation may leave unreferenced loose objects if STOP wins,
a peer disconnects, or the operation fails before CAS. The attempt fence
precedes object import. The shared sequencer and the final Core release
still govern the one exclusive link of the approved ref. A loose object
by itself conveys no publication or settlement evidence.

The explicit fixture still uses the one-owner repository contract. Its
privilege separation requires an implementation for shared physical
storage, an enforced exact-ref writer aperture, distinct-UID service
launch, and independent read-only verifier access. Production continues
using its existing admission and release configuration.
