# U13 offline diagnostic package evidence

This extends the existing U12 builder and launcher. It introduces no Core, provider, authority, approval, signer or runtime execution route. The package version is `0.2.0~u13.1`; the Python project stays `0.2.0`. The diagnostic launcher remains restricted to the existing inert fixture, imports, doctor and unbound console.

`scripts/build_deb_candidate.py` requires an explicit expected clean Git commit and tree. Before reading executable build inputs, it checks their Git blob identities, rejects symlinks, untracked changes and index flags that could conceal source drift, and uses the existing positive source allowlist and unchanged secret scanner. The same inputs, installed dependency closure, tool binaries and license evidence must still match after the build. The exact-version OS dependencies close only this diagnostic launcher's requirements; optional Python, browser and full desktop execution are excluded.

The builder records the actual CPython version/SOABI, installed OS dependency versions, tool package versions and SHA256 hashes of Python, dash, dirname, dpkg-deb, dpkg-query, Git and xz. It uses an explicit xz level and one compression thread, Git commit time as SOURCE_DATE_EPOCH, root archive ownership, fixed modes and no maintainer scripts. It builds in a new user-owned staging directory outside source. No package installation or live resolution occurs.

All three owned MIT notices remain in the payload and map to each source's SHA256 and SHA1. Installed distro copyright files are copied as separately hashed evidence. Missing copyright/license evidence blocks the build. Their sometimes mixed or ambiguous license expressions remain `NOASSERTION` / `REVIEW_REQUIRED`; a LicenseRef identifies the actual evidence text and is not an inferred license. The aggregate artifact has no blanket MIT conclusion. No third-party executable, Python environment, browser, personal HOME, private HAT, keys or developer configuration is bundled.

Three explicit distro notice owners are shared: libgcc-s1 uses gcc-14-base, libncursesw6 uses libtinfo6, and libpython3.12-stdlib uses libpython3.12-minimal. Both package identities must be in the pinned inventory at the same version. The canonical notice is read directly without following the distro alias directory; any unexpected link on that canonical path is denied.

The embedded `SOURCE_PROVENANCE.json` binds source inputs, ABI and toolchain. External `SBOM.spdx.json` is a deterministic SPDX 2.3 document describing the actual artifact SHA256, owned source files, exact OS dependency versions and build tools, relationships and preserved license evidence. `PROVENANCE.json` binds the artifact name/size/hash to the source commit/tree, SBOM hash, dependency inventory and build settings. External files avoid an impossible self-referential package hash. Validation implements a bounded SPDX 2.3 subset and reference/hash checks; an external full SPDX schema validator is not bundled or downloaded.

`scripts/verify_deb_candidate.py` requires the expected commit, tree and artifact SHA256 from the caller's trusted evidence. It reads bounded regular inputs, checks ar/xz/tar without extraction, rejects special files, links, private/traversal paths, duplicates, hidden trailing data, unexpected ownership/modes/epochs and maintainer scripts, and compares every payload byte and directory to a reconstruction from the pinned source. SPDX and provenance must equal canonical reconstruction. Names, dependency versions, ABI and licenses cannot be changed by editing sidecars. Verification uses the original build host's dependency/tool identities; it is not a portable clean-host certificate.

The parser supports bounded GNU long-name metadata emitted by dpkg-deb: one canonical ASCII name of at most 420 bytes, immediately followed by its matching regular-file/directory header. GNU link-name, PAX and other extensions are denied. Long names pass the same path/allowlist checks; all archive padding and trailing bytes must be zero.

Example for an already reviewed clean local commit (all paths are placeholders):

```text
python3 -B scripts/build_deb_candidate.py --expected-commit <SHA> --expected-tree <TREE> --output <new-external-directory>
python3 -B scripts/verify_deb_candidate.py --artifact <deb> --sbom <SBOM.spdx.json> --provenance <PROVENANCE.json> --expected-commit <SHA> --expected-tree <TREE> --expected-sha256 <trusted-package-SHA256>
```

The verifier accepts only diagnostic scope. `--scope release` always fails closed: no production trust path, signer verification or independent clean-host certification exists here. No fixture, claimed signature or model approval can lift that gate. These documents are unsigned evidence, not authenticity attestations.

Local two-build comparison and extraction smoke can establish `PASS_LOCAL_LIMITED` offline reproducibility on the measured host. PKG-02 remains limited to this provenance/SBOM implementation; signed distribution/P2/P3 remain NOT_ACCEPTED. PKG-03 supplies the [clean-host lifecycle plan](U13_CLEAN_HOST_TEST_PLAN.md); independent pilot acceptance is pending. P1/P2/P3/D4/D8, full runtime closure, managed browser and real Cockroach SQL need separate evidence. Publication remains BLOCKED_OR_PENDING.
