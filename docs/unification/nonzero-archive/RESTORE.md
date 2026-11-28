# Verified NonZero archival restore

On 28 November 2026, two fresh bare repositories restored the history reachable
from the 13 advertised refs using two physical media under the owner's control. Each restore
matched the [13 advertised refs](REFS_20261128.txt), contained 179 reachable
commits and 2674 reachable objects, and passed `git fsck --full`. The two
restores matched the current public source and the older saved manifest.
The primary and secondary copies also each restored 38 GitHub metadata
projections and passed their member checksums.

| Artifact | SHA-256 |
| --- | --- |
| Private R1 Git bundle | `84e5720c6cab3a8be59669a83396ed00018269be04e80e31bdc1e75d4828331e` |
| Advertised refs | `9cd19a7d2caa6c3bfc4bb88888e6928b3e642bd92b25442bac96863183f14c36` |
| Private R1 GitHub metadata archive | `41965734d0155f3e84b144dd61f8dc40e775e82d2fc1ba8db9a9e587bab5ab37` |
| Metadata member checksums | `6f27ca1686831c8c6bd7696ddab10da1b245cf32d98c9742b0b884d69151ab0c` |

The project retention custodian holds both R1 artifact locations and the
evidence catalog. The private bundle preserves history, including material
excluded from the historic submission distribution. Obtain the approved
copy from the custodian. [Legacy publication scope](https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent/blob/4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a/docs/submission/PUBLICATION_EXCLUSIONS.md)

## Restore and inspect

Use absolute paths to the existing bundle and to `REFS_20261128.txt`, then
restore into a fresh private bare repository. The manifest uses spaces
between OIDs and ref names and is sorted lexicographically.

```sh
set -eu
umask 077
printf '%s  %s\n' 84e5720c6cab3a8be59669a83396ed00018269be04e80e31bdc1e75d4828331e "$bundle" | sha256sum -c -
printf '%s  %s\n' 9cd19a7d2caa6c3bfc4bb88888e6928b3e642bd92b25442bac96863183f14c36 "$refs_manifest" | sha256sum -c -
scratch=$(mktemp -d)
git init --bare --initial-branch=main "$scratch/legacy.git"
git -C "$scratch/legacy.git" bundle verify "$bundle"
git -C "$scratch/legacy.git" fetch --no-tags "$bundle" '+refs/*:refs/*'
git -C "$scratch/legacy.git" for-each-ref --format='%(objectname) %(refname)' |
  LC_ALL=C sort > "$scratch/refs"
cmp "$refs_manifest" "$scratch/refs"
git -C "$scratch/legacy.git" fsck --full --no-dangling
test "$(git -C "$scratch/legacy.git" rev-list --all --count)" = 179
test "$(git -C "$scratch/legacy.git" rev-list --objects --all | wc -l)" = 2674
```

For metadata, supply absolute paths to the custodian archive and its separate
`github.SHA256SUMS`.

```sh
umask 077
printf '%s  %s\n' 41965734d0155f3e84b144dd61f8dc40e775e82d2fc1ba8db9a9e587bab5ab37 "$metadata_archive" | sha256sum -c -
printf '%s  %s\n' 6f27ca1686831c8c6bd7696ddab10da1b245cf32d98c9742b0b884d69151ab0c "$metadata_manifest" | sha256sum -c -
metadata_scratch=$(mktemp -d)
tar --no-same-owner --no-same-permissions -xzf "$metadata_archive" -C "$metadata_scratch"
cmp "$metadata_manifest" "$metadata_scratch/github.SHA256SUMS"
(cd "$metadata_scratch" && sha256sum -c --strict github.SHA256SUMS)
```

Keep the exact archived bytes when collecting a newer projection.
Repeat both checks on the second medium. Record date, media identifiers,
object counts and digest without exposing repository metadata beyond the
publication scope.

## Provenance and outstanding retention

The legacy `main` is `4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a`. W7A is
`392487849eddc7444f5159994b66b72e73f15934`. The restore matched all 412
main inventory entries. The [judging architecture](historical/SUBMISSION_ARCHITECTURE.md)
comes from `docs/submission/ARCHITECTURE.md` at legacy main (Git blob
`dad264744f5bc2b1b57b7af8687df03440734302`) under the
[original license](historical/LICENSE). Its relative claims reference
resolves to the pinned source. [Source document](https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent/blob/4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a/docs/submission/ARCHITECTURE.md)

The metadata readback covers the 38 archived projections. The latest known
GitHub deployment is `6378024487`, a success from 10 September 2026. The
Render management state, domains, consumers and rollback still require
a current read from the service custodian. The Git wiki read returned
repository not found. Projects V2 requires `read:project`. The owner still
holds the retention decision. Preserve both copies and the original repo.
[Deployment status](https://api.github.com/repos/luciferprosun/AIOA-NonZero-CloudOps-Agent/deployments/6378024487/statuses)
