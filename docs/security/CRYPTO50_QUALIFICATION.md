# Native crypto dependency candidate — post-submission

Base: main806a7a63ba2a9e7bcfc520dcb7d2efa0f788c6ef. This candidate changes the Native dependency to cryptography50.0.2. It does not upgrade the running Native, grant permissions or qualify LIVE execution. Merge and deployment require separate owner decisions.

The two existing key parsers now normalize UnsupportedAlgorithm to MobileError401 or GITHUB_PRIVATE_CREDENTIAL_REQUIRED. Device keys remain canonical P256 only; App signing keys remain RSA2048..4096. Real DER/PEM negative fixtures use public test data and must be refused before any HTTP request. RS256 signing and P256 verification retain existing positive and negative tests.

tests/requirements-crypto-linux.txt locks cryptography50.0.2, cffi2.1.1, pycparser3.12 and PyYAML6.0.3 to official wheel SHA256 values for CPython3.11/3.12 on Linuxx86_64/glibc. Core and MCP install that lock. Other platforms are not qualified by these CI jobs.

The Chrome harness uses system Python with an explicitly supplied private wheel site for that interpreter, never the ambient system crypto package. Install the lock into a fresh mode0700 target with pip --python /usr/bin/python3 --target, then invoke tests/mobile_device_console_browser.py --crypto-site <target>. CI contains the exact commands. The site is mounted readonly at /opt/aioa-test-crypto; the worker verifies versions and module origins before opening temporary fixture state. A strict content allowlist and refusal of links prevent replacing sealed source or fixture modules. Existing unshare-all, clearenv, cap-drop, no-home/no-host-network and source seals remain active.

CRYPTO_PROVENANCE separately reports the cryptography wheel backend OpenSSL and Python ssl's distribution OpenSSL; these are different TLS/crypto layers. Full Core/Native tests, isolated TLS/Chrome and installed wheel/sdist checks must pass on both supported interpreters for review. Passing offline tests is not an App credential check, production migration or agent WRITE receipt.

Upstream references: [PyPI50.0.2](https://pypi.org/project/cryptography/50.0.2/), [PyCA changelog](https://cryptography.io/en/stable/changelog/). Historical dependency records remain unchanged.
