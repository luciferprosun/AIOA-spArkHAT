# October 6 unlock and integration operator runbook

## 1. Explicit human release — mandatory first step

Obtain and record explicit human confirmation that the prior NVIDIA freeze is over. Calendar date alone is insufficient. This document grants no merge, live spending, deployment or publication authorization. Until that release, stop coding after the preparation pack; do not run the future commands below.

## 2. First five actions after release

1. Record the human release text/time and verify the clean source branch/ref state.
2. Capture immutable local refs and fetch remote refs (fetch only after the release).
3. Capture fetched active target SHA and preserve state externally; compare frozen refs/source identity and evidence hashes.
4. Run read-only preflight against the captured active target; review matrix/order/conflict forecast, then create a dedicated integration branch/worktree only if preflight is clean.
5. Run the active target offline baseline, then integrate I1 provider/config only and checkpoint after its tests pass.

## 3. Exact capture and fetch commands (post-release only)

Use a fresh directory; fail if it already exists. Commands below preserve local main and do not develop on it. Review configured remote origin before fetching; fetching can move origin/main as expected AFTER release only.

```bash
cd /media/l/LSC_DATA1/NVIDIA_NEBIUS/AIOA-spArkHAT-nebius
test "$(git branch --show-current)" = nebius-personal-ai
test -z "$(git status --porcelain)"
source_sha=$(git rev-parse HEAD)
local_main_sha=$(git rev-parse main)
old_origin_main_sha=$(git rev-parse origin/main)
capture_dir="/media/l/LSC_DATA1/NVIDIA_NEBIUS/PRE_OCT6_HANDOFF/unlock_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$capture_dir"
git show-ref > "$capture_dir/refs_before.txt"
git remote -v > "$capture_dir/remotes.txt"
# Review remotes.txt locally; URLs can contain credentials, do not publish it.
git fetch origin
target_sha=$(git rev-parse origin/main)
git show-ref > "$capture_dir/refs_after.txt"
printf '%s\n' "$source_sha" "$local_main_sha" "$old_origin_main_sha" "$target_sha" > "$capture_dir/captured_shas.txt"
test "$(git rev-parse HEAD)" = "$source_sha"
test "$(git rev-parse main)" = "$local_main_sha"
python3 scripts/oct6_integration_preflight.py --expected-main "$local_main_sha" --expected-origin-main "$target_sha" --target-sha "$target_sha" --format json > "$capture_dir/preflight.json"
python3 scripts/oct6_integration_preflight.py --expected-main "$local_main_sha" --expected-origin-main "$target_sha" --target-sha "$target_sha" --format human
```

If refs move between capture/preflight/integration, stop and recapture with explanation. PASS means only local inventory gates met, not compatibility or merge permission. Compare evidence SHA256 with preservation bundle CHECKSUMS.json. Inspect all preparation commits after sealed ea48547; they are docs/read-only tooling, not runtime source payload.

Review `OCT6_NEBIUS_INTEGRATION_MATRIX.md`, `OCT6_INTEGRATION_ORDER.md`, `OCT6_CONFLICT_FORECAST.md` and `OCT6_POST_UNLOCK_TEST_PLAN.md` before creating the worktree. Keep recorded source_sha immutable.

## 4. Dedicated integration worktree

```bash
integration_branch=integration/oct6-nebius-cloud-v1
integration_dir=/media/l/LSC_DATA1/NVIDIA_NEBIUS/AIOA-oct6-integration
git show-ref --verify --quiet "refs/heads/$integration_branch" && exit 1
test ! -e "$integration_dir"
git worktree add -b "$integration_branch" "$integration_dir" "$target_sha"
cd "$integration_dir"
test "$(git branch --show-current)" = "$integration_branch"
test "$(git rev-parse HEAD)" = "$target_sha"
test -z "$(git status --porcelain)"
```

This creates a future branch only after release. Run the active base's existing documented offline baseline before changing it. Missing dependencies or broken baseline block integration until explained; do not attribute pre-existing failures to the source port or count them PASS.

## 5. Integrate and checkpoint stage by stage

Perform I1–I8 exactly as listed in the integration-order document. Recreate selected final behavior against active Core; inspect source without checking it out using `git show <full-source-SHA>:<path>` or `git diff <source-parent> <source-SHA> -- <path>`. Do not cherry-pick all25 commits. Merge commits and intermediate fixture bug remain provenance, not integration payload.

After each reviewed stage, run its relevant tests in isolated credential-free temporary HOME, then static/security gates. Record exact output/counts and stop on FAIL/TIMEOUT/UNKNOWN. Stage commit must name original source SHAs and preserved authority contracts. Use explicit file staging, e.g. `git add <reviewed-stage-paths>` followed by `git commit -m '<stage-purpose referencing source SHAs>'`; no blanket add of local secrets/test state.

Capture checkpoint with `git rev-parse HEAD` and save it externally in the stage report. Before advancing verify clean worktree and compare local main/origin/main with captured values. New changes to origin/main require explicit reconciliation, not automatic rebasing.

## 6. Rollback without deleting provenance

For a committed failing stage on the dedicated integration branch:

```bash
test "$(git branch --show-current)" = integration/oct6-nebius-cloud-v1
# Replace with the reviewed integration commit, never an original source/main commit.
git revert <failed-integration-stage-SHA>
```

Rerun the last good gate and record revert SHA/cause. For dependent stages revert newest first after review. Preserve uncommitted failure state for analysis; create a separate worktree at the captured last-good SHA if needed. Do not reset, clean destructively, stash automatically, amend history or force-push.

## 7. Final decision gate

Fresh MEDIUM/FULL tests, static/secret checks, authority review, exact source/target/checkpoint identities and worktree cleanliness must all be reported. Review live/fixture distinctions, canonical learning claims and unknown outcomes. Obtain explicit human approval before any merge to main; merge execution is a later task. No direct main development, deployment, live inference, final video recording or Devpost submission follows automatically.

## 8. Preservation and current blockers

PRE_OCT6_HANDOFF contains an external timestamped git bundle (complete source history including merges), first-parent commit/file inventory, current preflight, sealed manifests/receipt and SHA256 checksums. It excludes local environments, credential files and private runtime state. Git format-patch alone would omit merge provenance; the bundle is the authoritative equivalent preservation artifact.

Known blockers: explicit freeze release not yet obtained; future active base unknown; Serverless credentials/deployment authorization absent; further paid model calls not authorized; distributed transactional leases/fencing/target deduplication unimplemented; vendor choice unresolved. None blocks preparation documentation.
