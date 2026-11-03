# Local QR encoder

`web/qr.js` is the Project Nayuki QR Code generator v1.8.0 ES6 release asset.

Source: https://github.com/nayuki/QR-Code-generator/releases/download/v1.8.0/qrcodegen-v1.8.0-es6.js

Official documentation: https://www.nayuki.io/page/qr-code-generator-library

Retrieved 2026-11-02 over verified HTTPS; 45,336 bytes. SHA-256:
`6a1116192ed1dd67fa1bf31e77f5817103d71c23bbac24c382e698b7668bdd01`.
The upstream asset does not publish a checksum/signature; this hash records exactly what was reviewed and vendored, not an upstream signature.

MIT license retained verbatim in the file header. No dependencies, network access or runtime CDN. The browser encodes only the public signed invite JSON, with medium error correction and a four-module white quiet zone. Phone signature/TLS/expiry checks remain mandatory; a QR is not authority.

Vendored adaptation: removed exactly five trailing whitespace bytes to satisfy repository whitespace checks; executable code and license unchanged. Bundled SHA-256: `5d65f10cbda9bc5f61df20e4dfb716ef3203b19f7daedb6cc7c0ae51193f033f` (45331 bytes).
