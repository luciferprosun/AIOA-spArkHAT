"""Canonical selective Git publisher port; inert previews and closed remote gate.

Lineage: AG04 GitPublishOperation/Registry and predict_public_commit contracts
(see docs/unification). Native effects use the existing Core and sandbox broker.
No W7A imports, second runtime, credential loader or direct remote subprocess.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from types import MappingProxyType

from runtime.mission.git_recipe import IDENT, canonical, git_object, require, sha256
from runtime.mission.warrant import require as core_require

REPOSITORY = "luciferprosun/AIOA-spArkHAT"
BRANCH_PREFIX = "codex/aioa-sensorbridge-"
DEMO_REPOSITORY = "luciferprosun/AIOA-spArkHAT-Meta-Hackathon-2026"
DEMO_REPOSITORY_ID = 1445911975
# v3 host fixture pin: Ubuntu git 1:2.43.0-1ubuntu7.4; dpkg -V git clean.
# Historical SyntheticGitPlan's v1 pin remains unchanged.
LOCAL_GIT_SHA256 = "eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201"


@dataclass(frozen=True, slots=True)
class LocalGitPlan:
    files: dict
    source_receipt_sha256: str
    operation_id: str

    def __post_init__(self):
        require(
            type(self.files) is dict and 0 < len(self.files) <= 8, "GIT_FILES_REQUIRED"
        )
        require(
            type(self.source_receipt_sha256) is str
            and re.fullmatch("[a-f0-9]{64}", self.source_receipt_sha256)
            and type(self.operation_id) is str
            and re.fullmatch("[a-f0-9]{32}", self.operation_id),
            "GIT_SOURCE_BINDING",
        )
        for name, data in self.files.items():
            require(
                type(name) is str
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name)
                and name not in (".git", "HEAD", "config")
                and type(data) is bytes
                and 0 < len(data) <= 8192
                and b"\0" not in data
                and data.endswith(b"\n"),
                "GIT_FILE_SCOPE_DENIED",
            )
            data.decode("utf-8")
        object.__setattr__(
            self, "files", MappingProxyType(dict(sorted(self.files.items())))
        )

    @property
    def branch(self):
        return BRANCH_PREFIX + self.operation_id

    @property
    def message(self):
        return (
            "aioa: add verified SensorBridge " + self.operation_id + " [skip ci]\n"
        ).encode()

    @property
    def tree_sha(self):
        return git_object(
            "tree",
            b"".join(
                b"100644 "
                + name.encode()
                + b"\0"
                + bytes.fromhex(git_object("blob", data))
                for name, data in self.files.items()
            ),
        )

    @property
    def commit_sha(self):
        return git_object(
            "commit",
            b"tree "
            + self.tree_sha.encode()
            + b"\nauthor "
            + IDENT
            + b"\ncommitter "
            + IDENT
            + b"\n\n"
            + self.message,
        )

    def diff_bytes(self):
        chunks = []
        for name, data in self.files.items():
            n = name.encode()
            blob = git_object("blob", data).encode()
            lines = data.splitlines(keepends=True)
            count = b"1" if len(lines) == 1 else b"1," + str(len(lines)).encode()
            chunks.append(
                b"diff --git a/"
                + n
                + b" b/"
                + n
                + b"\nnew file mode 100644\nindex "
                + b"0" * 40
                + b".."
                + blob
                + b"\n--- /dev/null\n+++ b/"
                + n
                + b"\n@@ -0,0 +"
                + count
                + b" @@\n"
                + b"".join(b"+" + line for line in lines)
            )
        return b"".join(chunks)

    def manifest(self):
        return {
            n: {"sha256": sha256(d), "bytes": len(d)} for n, d in self.files.items()
        }

    def plan_bytes(self):
        return canonical(
            {
                "schema": "aioa.local-git-plan.v3",
                "repository": REPOSITORY,
                "branch": self.branch,
                "expected_revision": "empty-repo-v1",
                "tree_sha": self.tree_sha,
                "commit_sha": self.commit_sha,
                "files": self.manifest(),
                "diff_sha256": sha256(self.diff_bytes()),
                "source_receipt_sha256": self.source_receipt_sha256,
                "operation_id": self.operation_id,
                "git_sha256": LOCAL_GIT_SHA256,
            }
        )

    @property
    def digest(self):
        return sha256(self.plan_bytes())

    def preview(self):
        return {
            **json.loads(self.plan_bytes()),
            "diff": self.diff_bytes().decode(),
            "authority": "NONE",
            "remote_write_allowed": False,
            "draft": True,
            "remote_gate": "BLOCKED_EXACT_OWNER_GO_AND_CREATE_ONLY_TRANSPORT",
            "force": False,
            "protected_branch_write": False,
            "model_has_credentials": False,
            "local_repository_profile": "DISPOSABLE_OFFLINE_FIXTURE",
            "canonical_base_verified": False,
        }

    def result_bytes(self):
        return canonical(
            {
                "schema": "aioa.local-git-result.v3",
                "plan_digest": self.digest,
                "branch": self.branch,
                "head": self.commit_sha,
                "tree": self.tree_sha,
                "status": "CLEAN",
                "files": self.manifest(),
                "source_receipt_sha256": self.source_receipt_sha256,
                "diff_sha256": sha256(self.diff_bytes()),
                "remote_write_performed": False,
            }
        )

    def recipe_spec(self):
        root = Path(__file__).parent
        return {
            "files": {
                "recipe.py": (root / "git_publish_worker.py").read_bytes(),
                "git_helpers.py": (root / "git_worker.py").read_bytes(),
                "plan.json": self.plan_bytes(),
                "commit-message.txt": self.message,
                "diff.patch": self.diff_bytes(),
                **{"source-" + n: d for n, d in self.files.items()},
            },
            "expected": {
                "result.json": self.result_bytes(),
                "diff.patch": self.diff_bytes(),
                **dict(self.files),
            },
        }


def _tree_hashes(entries):
    """Hash every directory from complete entries using existing Git hashing."""
    groups = {"": []}
    for path, (mode, kind, sha) in entries.items():
        parent, _, name = path.rpartition("/")
        require(
            not parent
            or parent in entries
            and entries[parent][:2] == ("040000", "tree"),
            "GITHUB_TREE_PARENT_DENIED",
        )
        groups.setdefault(parent, []).append((name, mode, kind, sha, path))
        if kind == "tree":
            groups.setdefault(path, [])
    hashes = {}
    for directory in sorted(
        groups, key=lambda p: len(p.split("/")) if p else 0, reverse=True
    ):
        chunks = []
        for name, mode, kind, sha, path in sorted(
            groups[directory],
            key=lambda e: e[0].encode() + (b"/" if e[2] == "tree" else b"\0"),
        ):
            object_sha = hashes[path] if kind == "tree" else sha
            chunks.append(
                ("40000" if kind == "tree" else mode).encode()
                + b" "
                + name.encode()
                + b"\0"
                + bytes.fromhex(object_sha)
            )
        hashes[directory] = git_object("tree", b"".join(chunks))
    return hashes


@dataclass(frozen=True, slots=True)
class GitTreeSnapshot:
    """Complete immutable tree evidence; truncated API lists are insufficient."""

    sha: str
    entries: dict

    def __post_init__(self):
        require(
            type(self.sha) is str and re.fullmatch("[a-f0-9]{40}", self.sha),
            "GITHUB_TREE_SHA_DENIED",
        )
        require(
            type(self.entries) is dict and len(self.entries) <= 4096,
            "GITHUB_TREE_LIMIT",
        )
        allowed = {
            ("100644", "blob"),
            ("100755", "blob"),
            ("120000", "blob"),
            ("040000", "tree"),
            ("160000", "commit"),
        }
        for path, value in self.entries.items():
            require(
                type(path) is str
                and 1 <= len(path.encode()) <= 512
                and "\0" not in path
                and all(p and p not in (".", "..") for p in path.split("/"))
                and len(path.split("/")) <= 32,
                "GITHUB_TREE_PATH_DENIED",
            )
            require(
                type(value) is tuple
                and len(value) == 3
                and value[:2] in allowed
                and type(value[2]) is str
                and re.fullmatch("[a-f0-9]{40}", value[2]),
                "GITHUB_TREE_ENTRY_DENIED",
            )
        hashes = _tree_hashes(self.entries)
        require(
            hashes[""] == self.sha
            and all(
                value[1] != "tree" or hashes[path] == value[2]
                for path, value in self.entries.items()
            ),
            "GITHUB_TREE_HASH_MISMATCH",
        )
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))

    @classmethod
    def from_github(cls, value, *, expected_sha):
        require(
            type(value) is dict
            and value.get("sha") == expected_sha
            and value.get("truncated") is False
            and type(value.get("tree")) is list
            and len(value["tree"]) <= 4096,
            "GITHUB_TREE_READBACK_DENIED",
        )
        entries = {}
        for entry in value["tree"]:
            require(
                type(entry) is dict
                and type(entry.get("path")) is str
                and entry["path"] not in entries,
                "GITHUB_TREE_ENTRY_DENIED",
            )
            entries[entry["path"]] = (
                entry.get("mode"),
                entry.get("type"),
                entry.get("sha"),
            )
        return cls(expected_sha, entries)

    def add_files(self, files):
        entries = dict(self.entries)
        for path, data in files.items():
            require(
                type(path) is str
                and path.startswith("agent-demo/")
                and path not in entries
                and type(data) is bytes,
                "GITHUB_CREATE_ONLY_REQUIRED",
            )
            parts = path.split("/")
            for index in range(1, len(parts)):
                parent = "/".join(parts[:index])
                if parent in entries:
                    require(
                        entries[parent][:2] == ("040000", "tree"),
                        "GITHUB_TREE_PARENT_DENIED",
                    )
                else:
                    entries[parent] = ("040000", "tree", "0" * 40)
            entries[path] = ("100644", "blob", git_object("blob", data))
        hashes = _tree_hashes(entries)
        for path, value in tuple(entries.items()):
            if value[1] == "tree":
                entries[path] = ("040000", "tree", hashes[path])
        return GitTreeSnapshot(hashes[""], entries)


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteGitPlan:
    """Pure remote review data. Construction grants no dispatch capability.

    Model content and native provenance are separate inputs. Base/source/branch
    bindings cannot be supplied through model JSON. Existing local plan and
    network-OFF recipe contracts are unchanged.
    """

    files: dict
    title: str
    body: str
    operation_id: str
    issued_at: int
    base_sha: str
    base_tree_sha: str
    source_sha: str
    capsule_digest: str
    source_reply_sha256: str
    source_receipt_sha256: str

    def __post_init__(self):
        require(
            type(self.issued_at) is int and 1 <= self.issued_at <= 253402300799,
            "GITHUB_TIME_BINDING",
        )
        for name, size in (
            ("operation_id", 32),
            ("base_sha", 40),
            ("base_tree_sha", 40),
            ("source_sha", 40),
            ("capsule_digest", 64),
            ("source_reply_sha256", 64),
            ("source_receipt_sha256", 64),
        ):
            value = getattr(self, name)
            require(
                type(value) is str
                and re.fullmatch("[a-f0-9]{" + str(size) + "}", value),
                "GITHUB_SOURCE_BINDING",
            )
        require(
            type(self.title) is str
            and self.title.strip()
            and len(self.title.encode()) <= 160
            and all(ord(c) >= 32 and ord(c) != 127 for c in self.title),
            "GITHUB_TITLE_DENIED",
        )
        require(
            type(self.body) is str
            and self.body.strip()
            and len(self.body.encode()) <= 4000
            and all(c in "\n\t" or ord(c) >= 32 and ord(c) != 127 for c in self.body),
            "GITHUB_BODY_DENIED",
        )
        require(
            type(self.files) is dict and 1 <= len(self.files) <= 4,
            "GITHUB_FILES_REQUIRED",
        )
        clean = {}
        folded = set()
        reserved = {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10)),
        }
        for path, data in self.files.items():
            require(type(path) is str and len(path) <= 160, "GITHUB_PATH_DENIED")
            parts = path.split("/")
            require(
                2 <= len(parts) <= 4
                and parts[0] == "agent-demo"
                and all(
                    re.fullmatch("[A-Za-z0-9][A-Za-z0-9_-]{0,47}", p)
                    for p in parts[1:-1]
                )
                and re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}\.(?:md|txt|py)", parts[-1]
                )
                and all(p.split(".")[0].lower() not in reserved for p in parts)
                and path.lower() not in folded,
                "GITHUB_PATH_DENIED",
            )
            require(
                type(data) is bytes
                and 1 <= len(data) <= 8192
                and data.endswith(b"\n")
                and b"\x00" not in data
                and b"\r" not in data,
                "GITHUB_CONTENT_DENIED",
            )
            content = data.decode("utf-8")
            require(
                all(c in "\n\t" or ord(c) >= 32 and ord(c) != 127 for c in content),
                "GITHUB_CONTENT_DENIED",
            )
            clean[path] = data
            folded.add(path.lower())
        require(sum(map(len, clean.values())) <= 16384, "GITHUB_CONTENT_LIMIT")
        object.__setattr__(self, "files", MappingProxyType(dict(sorted(clean.items()))))

    @classmethod
    def from_model(cls, raw, **native_binding):
        from runtime.mobile_gateway.wire import RESPONSE_LIMIT, strict_json

        require(type(raw) is bytes and len(raw) <= 32768, "GITHUB_PROPOSAL_LIMIT")
        value = strict_json(raw, limit=RESPONSE_LIMIT)
        require(
            type(value) is dict
            and set(value)
            == {"schema", "operation", "target_repo", "files", "title", "body"}
            and value["schema"] == "aioa.muse.github-change.v1"
            and value["operation"] == "code.commit_draft_pr"
            and value["target_repo"] == DEMO_REPOSITORY,
            "GITHUB_PROPOSAL_SCOPE_DENIED",
        )
        require(
            type(value["files"]) is dict
            and all(type(v) is str for v in value["files"].values()),
            "GITHUB_FILES_REQUIRED",
        )
        return cls(
            files={k: v.encode("utf-8") for k, v in value["files"].items()},
            title=value["title"],
            body=value["body"],
            **native_binding,
        )

    @property
    def branch(self):
        return "aioa/muse-" + self.operation_id

    @property
    def message(self):
        return self.title + "\n\nAIOA operation: " + self.operation_id + "\n"

    def commit_payload(self, tree_sha):
        from datetime import datetime

        require(
            type(tree_sha) is str and re.fullmatch("[a-f0-9]{40}", tree_sha),
            "GITHUB_TREE_SHA_DENIED",
        )
        identity = {
            "name": "AIOA Core",
            "email": "aioa-core@aioa.invalid",
            "date": datetime.fromtimestamp(self.issued_at, UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        return {
            "message": self.message,
            "tree": tree_sha,
            "parents": [self.base_sha],
            "author": dict(identity),
            "committer": dict(identity),
        }

    def commit_sha_for_tree(self, tree_sha):
        self.commit_payload(tree_sha)
        identity = (
            b"AIOA Core <aioa-core@aioa.invalid> "
            + str(self.issued_at).encode()
            + b" +0000"
        )
        raw = (
            b"tree "
            + tree_sha.encode()
            + b"\nparent "
            + self.base_sha.encode()
            + b"\nauthor "
            + identity
            + b"\ncommitter "
            + identity
            + b"\n\n"
            + self.message.encode()
        )
        return git_object("commit", raw)

    def manifest(self):
        return {
            p: {
                "sha256": sha256(data),
                "git_blob_sha": git_object("blob", data),
                "bytes": len(data),
                "mode": "100644",
            }
            for p, data in self.files.items()
        }

    def diff_bytes(self):
        from difflib import unified_diff

        return "".join(
            "diff --git a/"
            + p
            + " b/"
            + p
            + "\nnew file mode 100644\n"
            + "".join(
                unified_diff(
                    [],
                    data.decode().splitlines(keepends=True),
                    fromfile="/dev/null",
                    tofile="b/" + p,
                )
            )
            for p, data in self.files.items()
        ).encode()

    def payload(self):
        return {
            "schema": "aioa.remote-git-plan.v1",
            "repository": DEMO_REPOSITORY,
            "repository_id": DEMO_REPOSITORY_ID,
            "operation": "code.commit_draft_pr",
            "operation_id": self.operation_id,
            "issued_at": self.issued_at,
            "commit_identity": self.commit_payload(self.base_tree_sha)["author"],
            "base_ref": "main",
            "base_sha": self.base_sha,
            "base_tree_sha": self.base_tree_sha,
            "branch": self.branch,
            "commit_message": self.message,
            "pr_title": self.title,
            "pr_body": self.body,
            "draft": True,
            "maintainer_can_modify": False,
            "force": False,
            "merge": False,
            "api_request_limit": 48,
            "write_retry_limit": 0,
            "files": {p: data.decode() for p, data in self.files.items()},
            "manifest": self.manifest(),
            "diff_sha256": sha256(self.diff_bytes()),
            "source_sha": self.source_sha,
            "capsule_digest": self.capsule_digest,
            "source_reply_sha256": self.source_reply_sha256,
            "source_receipt_sha256": self.source_receipt_sha256,
        }

    @property
    def digest(self):
        return sha256(canonical(self.payload()))

    def preview(self):
        return {
            **self.payload(),
            "plan_digest": self.digest,
            "diff": self.diff_bytes().decode(),
            "authority": "NONE",
            "execution_authorized": False,
        }


class RemotePublishBoundary:
    """No default network actuator or authority inferred from a preview.

    An actual create-only transport, credentials and exact per-step native GO
    remain a separate gate. Observations below classify uncertainty, not effects.
    """

    def dispatch(self, operation, proposal):
        raise ValueError("GITHUB_REMOTE_BLOCKED_SEPARATE_EXACT_OWNER_GO")

    @staticmethod
    def classify_observation(status):
        state = (
            "DENIED"
            if status in (401, 403)
            else "BLOCKED_RATE_LIMIT"
            if status == 429
            else "UNKNOWN"
        )
        return {
            "state": state,
            "automatic_retry": False,
            "effect_verified": False,
            "authority": "NONE",
        }


class CoreRemoteGitRoute:
    """Registered remote slice on the existing Core journal and ServiceGuard.

    Construction is Native-only. api_factory/check/target_guard are trusted host
    ports, never values supplied by a model or HTTP client. Credential creation
    is deferred until the existing owner-wide START barrier has admitted the
    exact operation. The route owns no separate Core, governor or state store.
    """

    @staticmethod
    def prepare_patchset(
        base_root, final_root, *, source, task, worker_session_id, capsule_digest
    ):
        """General preparation is inert; it cannot widen the registered profile."""
        from runtime.mission.patchset import BoundedPatchSetPolicy, _snapshot

        policy = BoundedPatchSetPolicy()
        patch = policy.evaluate(
            base_root,
            final_root,
            source=source,
            task=task,
            worker_session_id=worker_session_id,
        )
        observed = _snapshot(final_root)
        core_require(observed.digest == patch.final_tree_sha256, "GIT_PATCH_TREE_DRIFT")
        images = tuple(
            (
                change.path,
                None
                if change.operation == "DELETE"
                else observed.files[change.path].content,
            )
            for change in patch.files
        )
        original = _snapshot(base_root)
        core_require(original.digest == patch.base_tree_sha256, "GIT_PATCH_TREE_DRIFT")
        preimages = tuple(
            (
                change.path,
                None
                if change.operation == "ADD"
                else original.files[change.path].content,
            )
            for change in patch.files
        )
        policy.recheck(
            patch,
            base_root=base_root,
            final_root=final_root,
            source=source,
            task=task,
            worker_session_id=worker_session_id,
        )
        return VerifiedPatchSet(patch, images, capsule_digest, preimages)

    @classmethod
    def for_local_patch(
        cls,
        principal,
        journal,
        *,
        capsules,
        preparation,
        profile,
        source_snapshot,
        source_repository,
        target_repository,
        check,
        target_guard,
    ):
        """Native-only, versioned disposable bare profile on THIS registered route."""
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.intent import CoreIntentJournal
        from runtime.mission.patch_capsule import KIND, CorePatchCapsules
        from runtime.mission.project_recipe import PythonRepositoryRecipe

        core_require(
            type(journal) is CoreIntentJournal
            and type(capsules) is CorePatchCapsules
            and capsules.journal is journal,
            "EXISTING_CORE_REQUIRED",
        )
        core_require(
            type(preparation) is VerifiedPatchSet
            and type(profile) is PythonRepositoryRecipe
            and type(source_snapshot) is GitSourceSnapshot
            and callable(check)
            and callable(target_guard),
            "GIT_LOCAL_PROFILE_REQUIRED",
        )
        preparation.__post_init__()
        profile.validate_patch(preparation.patchset)

        def load(tx):
            from runtime.mission.coding_tasks import KIND as TASK_KIND
            from runtime.mission.coding_tasks import decode_coding_task_row

            row = tx.get(
                RecordKind.OPERATION,
                canonical_sha256([KIND, preparation.capsule_digest]),
            )
            core_require(row is not None, "CAPSULE_REQUIRED")
            capsule = capsules._decode(row)
            taskrow = tx.get(
                RecordKind.OPERATION, canonical_sha256([TASK_KIND, capsule.task_id])
            )
            _, coding, task = decode_coding_task_row(
                taskrow, capsule.task_id, capsules.identity.spki
            )
            last = coding["receipts"][-1]["receipt"]
            core_require(
                task.digest == capsule.task_digest
                and last["capsule_digest"] == capsule.digest
                and last["state"]
                in ("REVIEW_REQUIRED", "APPROVED", "APPLYING", "UNKNOWN", "VERIFIED"),
                "GIT_CODING_TASK_INACTIVE",
            )
            return capsule, last["state"]

        capsule, state = journal._run(principal, Capability.COMMIT, load)
        historical = state in ("APPLYING", "UNKNOWN", "VERIFIED")
        patch = preparation.patchset
        core_require(
            (
                capsule.patchset_sha256,
                capsule.source_base_sha,
                capsule.base_tree_sha256,
                capsule.final_tree_sha256,
                capsule.test_profile_digest,
                capsule.worker_session_id,
            )
            == (
                patch.patchset_sha256,
                source_snapshot.source_base_sha,
                source_snapshot.export_tree_sha256,
                patch.final_tree_sha256,
                profile.digest,
                patch.worker_session_id,
            )
            and capsule.repository_id == source_snapshot.repository_id
            and capsule.workspace_id == source_snapshot.workspace_id,
            "GIT_CAPSULE_PATCH_BINDING",
        )
        if not historical:
            source_snapshot.verify(source_repository)
            target = GitSourceSnapshot.capture(
                target_repository,
                expected_sha=source_snapshot.source_base_sha,
                repository_id=source_snapshot.repository_id,
                workspace_id=source_snapshot.workspace_id,
            )
            core_require(target == source_snapshot, "GIT_TARGET_SOURCE_BINDING")
        plan = LocalPatchGitPlan(
            source_snapshot,
            preparation,
            profile.digest,
            _git_target_identity(target_repository),
            capsule.issued_at,
        )
        core_require(
            capsule.target_fingerprint == plan.target_fingerprint
            and capsule.target_revision == "git-" + source_snapshot.source_base_sha,
            "GIT_CAPSULE_TARGET_BINDING",
        )
        instance = cls.__new__(cls)
        instance.journal, instance.capsules, instance.capsule = (
            journal,
            capsules,
            capsule,
        )
        instance.plan, instance.identity, instance.mode = (
            plan,
            capsules.identity,
            "LOCAL_PATCH_FIXTURE",
        )
        instance.core, instance.runner, instance.scope = (
            journal.ledger.core,
            journal.ledger.runner,
            journal.ledger.scope,
        )
        instance.source_repository, instance.target_repository = (
            Path(source_repository),
            Path(target_repository),
        )
        instance.target_guard, instance.owner_check = target_guard, check
        instance.historical_operation = None

        def proofs(tx):
            instance._local_proofs(tx, historical=historical)
            return instance._local_history(tx) if historical else None

        instance.historical_operation = journal._run(
            principal, Capability.COMMIT, proofs
        )
        instance.check = (
            instance._historical_local_check if historical else instance._local_check
        )
        instance.check()
        return instance

    def _local_proofs(self, tx, *, historical=False):
        from lab.archaioa.warrant import EffectWarrant
        from runtime.memory_patch.contracts.serialization import (
            canonical_json_bytes,
            canonical_sha256,
        )
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.coding_tasks import KIND as TASK_KIND
        from runtime.mission.coding_tasks import decode_coding_task_row
        from runtime.mission.liability import Reconciliation
        from runtime.mission.patch_capsule import KIND

        c = self.capsule
        taskrow = tx.get(RecordKind.OPERATION, canonical_sha256([TASK_KIND, c.task_id]))
        _, coding, task = decode_coding_task_row(taskrow, c.task_id, self.identity.spki)
        last = coding["receipts"][-1]["receipt"]
        core_require(
            task.digest == c.task_digest
            and last["capsule_digest"] == c.digest
            and last["state"]
            in (
                ("APPLYING", "UNKNOWN", "VERIFIED")
                if historical
                else ("REVIEW_REQUIRED", "APPROVED", "APPLYING")
            ),
            "GIT_CODING_TASK_INACTIVE",
        )
        looprow = tx.get(
            RecordKind.OPERATION,
            canonical_sha256(["aioa.coding-loop.v1", c.task_digest]),
        )
        core_require(looprow is not None, "GIT_CORE_LOOP_REQUIRED")
        loopdata = json.loads(canonical_json_bytes(looprow.payload))
        loop = loopdata.get("result", {})
        loop_digest = loop.pop("receipt_sha256", None)
        core_require(
            loopdata.get("schema") == "aioa.coding-loop.v1"
            and loopdata.get("task_digest") == c.task_digest
            and loop_digest == c.loop_receipt_sha256
            and canonical_sha256(loop) == c.loop_receipt_sha256
            and loop.get("status") == "PATCH_READY",
            "GIT_CORE_LOOP_BINDING",
        )
        row = tx.get(RecordKind.OPERATION, canonical_sha256([KIND, c.digest]))
        core_require(
            row is not None and self.capsules._decode(row) == c, "GIT_CAPSULE_REQUIRED"
        )
        key = canonical_sha256(["aioa.materialization.v1", c.patchset_sha256])
        row = tx.get(RecordKind.OPERATION, key)
        core_require(row is not None, "GIT_MATERIALIZATION_REQUIRED")
        data = row.payload
        core_require(
            data.get("schema") == "aioa.materialization.v1"
            and data.get("state") == "MATERIALIZED"
            and data.get("task_digest") == c.task_digest
            and data.get("patchset_sha256") == c.patchset_sha256
            and data.get("profile_digest") == c.test_profile_digest
            and data.get("source_base_sha") == c.source_base_sha
            and data.get("source_readback_digest") == self.plan.source.digest
            and data.get("final_tree_sha256") == c.final_tree_sha256,
            "GIT_MATERIALIZATION_BINDING",
        )
        proofs = [data]
        for stage, wd, ed in zip(
            ("FAST_TESTS", "TARGETED_TESTS", "FINAL_TESTS"),
            c.validation_warrants,
            c.validation_receipts,
        ):
            row = tx.get(
                RecordKind.OPERATION,
                canonical_sha256(["aioa.trusted-validation.v1", wd]),
            )
            core_require(row is not None, "GIT_VALIDATION_REQUIRED")
            data = row.payload
            core_require(
                data.get("trusted_observer") == "EXTERNAL_JSON_ORACLE"
                and data.get("stage") == stage
                and data.get("status") == "PASS"
                and data.get("exit_code") == 0
                and data.get("patchset_sha256") == c.patchset_sha256
                and data.get("profile_digest") == c.test_profile_digest
                and data.get("warrant_digest") == wd
                and data.get("evidence_digest") == ed
                and data.get("source_base_sha") == c.source_base_sha,
                "GIT_VALIDATION_BINDING",
            )
            proofs.append(data)
        for data in proofs:
            warrant = EffectWarrant.from_dict(
                json.loads(canonical_json_bytes(data["warrant"]))
            )
            core_require(
                warrant.digest() == data["warrant_digest"], "GIT_PROOF_WARRANT_BINDING"
            )
            _, intent = self.journal._load(tx, warrant)
            core_require(
                intent is not None and intent["resolution"] is not None,
                "GIT_UNKNOWN_PROOF",
            )
            resolution = Reconciliation.from_dict(intent["resolution"])
            core_require(
                resolution.outcome.to_dict()["contract_type"] == "Applied"
                and resolution.receipt.digest == "sha256:" + data["evidence_digest"]
                and resolution.operation_digest == warrant.operation_hash,
                "GIT_UNKNOWN_PROOF",
            )

    def _local_history(self, tx):
        """An inert binding to an existing canonical START, never new authority."""
        from runtime.memory_patch.contracts.serialization import (
            canonical_json_bytes,
            canonical_sha256,
        )
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.intent import KIND, LOCAL_ZERO_KIND

        row = tx.get(
            RecordKind.OPERATION,
            "github-step-" + self.plan.operation_id + "-local_patch",
        )
        core_require(
            row is not None
            and row.payload.get("schema") == "aioa.local-patch-step.v1"
            and row.payload.get("plan_digest") == self.plan.digest,
            "GIT_DISPATCH_PROVENANCE_REQUIRED",
        )
        key = canonical_sha256(
            (KIND, self.scope, self.capsule.task_id, row.payload["operation_hash"])
        )
        intent_row = tx.get(RecordKind.OPERATION, key)
        core_require(intent_row is not None, "GIT_INTENT_REQUIRED")
        intent = intent_row.payload
        operation = intent.get("operation", {})
        payload = operation.get("payload", {})
        core_require(
            intent.get("schema") == LOCAL_ZERO_KIND
            and intent.get("warrant_digest") == row.payload.get("warrant_digest")
            and "sha256:" + canonical_sha256(operation) == row.payload["operation_hash"]
            and type(payload.get("principal_session_id")) is str
            and type(payload.get("policy_epoch")) is int
            and operation
            == self.operation(payload["principal_session_id"], payload["policy_epoch"]),
            "GIT_INTENT_REQUIRED",
        )
        return json.loads(canonical_json_bytes(operation))

    def _historical_local_check(self):
        self.owner_check()
        core_require(
            _git_target_identity(self.target_repository) == self.plan.target_identity,
            "GIT_TARGET_MOVED",
        )

    def _prospective_local(self):
        core_require(
            getattr(self, "historical_operation", None) is None,
            "GIT_HISTORICAL_READ_ONLY",
        )

    def _local_check(self):
        self._prospective_local()
        self.owner_check()
        self.capsules._fresh(self.capsule)
        self.plan.source.verify(self.source_repository)
        core_require(
            _git_target_identity(self.target_repository) == self.plan.target_identity,
            "GIT_TARGET_MOVED",
        )
        current = GitSourceSnapshot.capture(
            self.target_repository,
            expected_sha=self.plan.source.source_base_sha,
            repository_id=self.plan.source.repository_id,
            workspace_id=self.plan.source.workspace_id,
            expected_target_identity=self.plan.target_identity,
        )
        core_require(current == self.plan.source, "GIT_TARGET_SOURCE_DRIFT")

    def approve_local_patch(self, principal, warrant, *, controller):
        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.coding_tasks import CoreCodingTasks

        self.core.require(principal, Capability.OWNER_APPROVAL, scope=self.scope)
        core_require(self.mode == "LOCAL_PATCH_FIXTURE", "GIT_LOCAL_PROFILE_REQUIRED")
        self._prospective_local()
        core_require(
            type(controller) is CoreCodingTasks
            and controller.journal is self.journal
            and controller.capsules is self.capsules,
            "EXISTING_CORE_REQUIRED",
        )
        with self.target_guard():
            self.check()
            operation = self.operation(principal.actor_session_id, warrant.lease_epoch)
            self._local_warrant(warrant, operation)

            def approve(tx):
                self._local_proofs(tx)
                _, data, _ = controller._load(tx, self.capsule.task_id)
                core_require(
                    data["receipts"][-1]["receipt"]["state"]
                    in ("REVIEW_REQUIRED", "APPROVED"),
                    "CODING_TASK_INACTIVE",
                )
                ledger = self.journal.ledger
                if tx.get(RecordKind.OPERATION, ledger._key(warrant)) is None:
                    ledger.approve_in_transaction(tx, warrant)
                else:
                    # Exact recovery of an existing unconsumed owner witness,
                    # including a pre-fix split commit. Never renew, attenuate,
                    # un-revoke or transfer a witness to another session.
                    ledger.require_active_in_transaction(tx, warrant)
                return controller._append_transition(
                    tx,
                    self.capsule.task_id,
                    ("REVIEW_REQUIRED",),
                    "APPROVED",
                    capsule_digest=self.capsule.digest,
                )

            return self.journal._run(principal, Capability.OWNER_APPROVAL, approve)

    def _local_warrant(self, warrant, operation):
        from runtime.memory_patch.contracts.serialization import canonical_sha256

        core_require(
            warrant.operation_class == "GIT_COMMIT"
            and warrant.task_id == self.capsule.task_id
            and warrant.operation_hash == "sha256:" + canonical_sha256(operation)
            and warrant.target_fingerprint == self.plan.target_fingerprint
            and warrant.expected_target_revision
            == "git-" + self.plan.source.source_base_sha
            and warrant.decision_dependency_root == self.dependency_root
            and int(warrant.expires_at.timestamp()) <= self.capsule.expires_at
            and (warrant.expires_at - warrant.issued_at).total_seconds() <= 300,
            "GIT_EXACT_APPROVAL_REQUIRED",
        )

    def _dispatch_local_patch(self, principal, warrant, operation, release, cancel):
        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import RecordKind

        self._prospective_local()
        key = "github-step-" + self.plan.operation_id + "-local_patch"

        def mark(tx):
            self.validate(tx, warrant, operation, consumed=True)
            _, intent = self.journal._load(tx, warrant)
            core_require(
                intent is not None and intent["resolution"] is None,
                "GIT_INTENT_REQUIRED",
            )
            if tx.get(RecordKind.OPERATION, key) is not None:
                return False
            self._save(
                tx,
                key,
                {
                    "schema": "aioa.local-patch-step.v1",
                    "state": "GITHUB_STEP_UNKNOWN",
                    "warrant_digest": warrant.digest(),
                    "operation_hash": warrant.operation_hash,
                    "plan_digest": self.plan.digest,
                    "automatic_retry": False,
                },
            )
            return True

        core_require(
            self.journal._run(principal, Capability.COMMIT, mark),
            "GIT_UNKNOWN_NO_RETRY",
        )
        # Only fixed object plumbing and create-ref CAS; no checkout, hooks,
        # filters, shell, configurable argv, network, main update or force.
        for kind, data, expected in self.plan.objects:
            release()
            actual = (
                _bounded_git(
                    self.target_repository,
                    ("hash-object", "-w", "-t", kind, "--stdin"),
                    data=data,
                    cancel=cancel,
                    expected_target_identity=self.plan.target_identity,
                )
                .decode()
                .strip()
            )
            core_require(actual == expected, "GIT_OBJECT_READBACK")
        release()
        _bounded_git(
            self.target_repository,
            ("update-ref", self.plan.ref, self.plan.commit_sha, "0" * 40),
            cancel=cancel,
            expected_target_identity=self.plan.target_identity,
        )
        release()
        return self._complete_local_patch(principal, warrant, historical=False)

    def _complete_local_patch(self, principal, warrant, *, historical):
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.outcome import Applied
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.liability import Reconciliation

        core_require(
            _git_target_identity(self.target_repository) == self.plan.target_identity,
            "GIT_TARGET_MOVED",
        )
        observed = GitSourceSnapshot.capture(
            self.target_repository,
            expected_sha=self.plan.commit_sha,
            repository_id=self.plan.source.repository_id,
            workspace_id=self.plan.source.workspace_id,
            ref=self.plan.ref,
            expected_target_identity=self.plan.target_identity,
        )
        core_require(
            observed.files == self.plan.files
            and observed.git_tree_sha == self.plan.tree_sha
            and _bounded_git(
                self.target_repository,
                ("cat-file", "commit", self.plan.commit_sha),
                expected_target_identity=self.plan.target_identity,
            )
            == self.plan.commit_data,
            "GIT_COMMIT_READBACK",
        )
        receipt = {
            "schema": "aioa.local-patch-git-receipt.v1",
            "state": "LOCAL_GIT_VERIFIED",
            "plan_digest": self.plan.digest,
            "capsule_digest": self.capsule.digest,
            "patchset_sha256": self.capsule.patchset_sha256,
            "warrant_digest": warrant.digest(),
            "source_base_sha": self.plan.source.source_base_sha,
            "source_readback_digest": self.plan.source.digest,
            "commit_sha": self.plan.commit_sha,
            "tree_sha": self.plan.tree_sha,
            "ref": self.plan.ref,
            "readback_digest": observed.digest,
            "remote_write_performed": False,
            "automatic_retry": False,
        }
        result = {"receipt": receipt, "signature": self.identity.sign(receipt)}

        def save(tx):
            if historical:
                self._local_proofs(tx, historical=True)
                self._local_history(tx)
            _, intent = self.journal._load(tx, warrant)
            core_require(
                intent is not None
                and intent["operation"]
                == self.operation(
                    intent["operation"]["payload"]["principal_session_id"],
                    warrant.lease_epoch,
                ),
                "GIT_INTENT_REQUIRED",
            )
            if intent["resolution"] is not None:
                return self.journal._public(intent)
            if not historical:
                self.validate(tx, warrant, intent["operation"], consumed=True)
            row = tx.get(
                RecordKind.OPERATION,
                "github-step-" + self.plan.operation_id + "-local_patch",
            )
            core_require(
                row is not None
                and row.payload["warrant_digest"] == warrant.digest()
                and row.payload["operation_hash"] == warrant.operation_hash
                and row.payload["plan_digest"] == self.plan.digest,
                "GIT_DISPATCH_PROVENANCE_REQUIRED",
            )
            self._save(
                tx,
                "github-result-" + self.plan.operation_id,
                {
                    "schema": "aioa.local-patch-result.v1",
                    "state": "GITHUB_VERIFIED",
                    "result": result,
                },
            )
            proof = EvidenceRef(
                "git-receipt-" + self.plan.operation_id,
                "receipt",
                "sha256:" + canonical_sha256(result),
                "v1",
            )
            read = EvidenceRef(
                "git-read-" + self.plan.operation_id,
                "independent-readback",
                "sha256:" + observed.digest,
                "v1",
            )
            resolution = Reconciliation(
                warrant.operation_hash, Applied(proof.evidence_id), proof, read
            )
            return self.journal.apply_resolution_in_transaction(
                tx, warrant, self.journal.governor._load(tx)["epoch"], resolution
            )

        return self.journal._run(principal, Capability.COMMIT, save)

    def __init__(
        self, journal, *, plan, base, identity, api_factory, check, target_guard, mode
    ):
        from runtime.mission.intent import CoreIntentJournal
        from runtime.mobile_gateway.wire import Identity

        core_require(
            type(journal) is CoreIntentJournal
            and type(plan) is RemoteGitPlan
            and type(base) is GitTreeSnapshot
            and base.sha == plan.base_tree_sha
            and type(identity) is Identity
            and callable(api_factory)
            and callable(check)
            and callable(target_guard)
            and mode in ("LIVE", "OFFLINE_FIXTURE"),
            "GITHUB_NATIVE_ROUTE_REQUIRED",
        )
        self.journal, self.plan, self.base, self.identity = (
            journal,
            plan,
            base,
            identity,
        )
        self.core, self.runner, self.scope = (
            journal.ledger.core,
            journal.ledger.runner,
            journal.ledger.scope,
        )
        self.api_factory, self.check, self.target_guard, self.mode = (
            api_factory,
            check,
            target_guard,
            mode,
        )
        self.tree = base.add_files(plan.files)

    @property
    def dependency_root(self):
        from lab.archaioa.decision_root import DecisionDependencyRoot
        from lab.archaioa.evidence import EvidenceRef

        if self.mode == "LOCAL_PATCH_FIXTURE":
            return DecisionDependencyRoot(
                (
                    EvidenceRef("git-plan", "task", "sha256:" + self.plan.digest, "v1"),
                    EvidenceRef(
                        "git-capsule", "receipt", "sha256:" + self.capsule.digest, "v1"
                    ),
                    EvidenceRef(
                        "git-source",
                        "context",
                        "sha256:" + self.plan.source.digest,
                        self.plan.source.source_base_sha,
                    ),
                )
            )
        return DecisionDependencyRoot(
            (
                EvidenceRef("github-plan", "task", "sha256:" + self.plan.digest, "v1"),
                EvidenceRef(
                    "muse-receipt",
                    "receipt",
                    "sha256:" + self.plan.source_receipt_sha256,
                    "v1",
                ),
                EvidenceRef(
                    "native-source",
                    "context",
                    "sha256:" + self.plan.capsule_digest,
                    self.plan.source_sha,
                ),
            )
        )

    def operation(self, session_id, epoch):
        from runtime.memory_patch.contracts.serialization import canonical_sha256

        if self.mode == "LOCAL_PATCH_FIXTURE":
            return {
                "operation_class": "GIT_COMMIT",
                "target_fingerprint": self.plan.target_fingerprint,
                "expected_target_revision": "git-" + self.plan.source.source_base_sha,
                "payload": {
                    "schema": "aioa.local-operation.v2",
                    "principal_session_id": session_id,
                    "policy_epoch": epoch,
                    "profile": "DISPOSABLE_BARE_PATCH_V1",
                    "plan_digest": self.plan.digest,
                    "capsule_digest": self.capsule.digest,
                    "patchset_sha256": self.capsule.patchset_sha256,
                    "source_base_sha": self.plan.source.source_base_sha,
                    "commit_sha": self.plan.commit_sha,
                    "tree_sha": self.plan.tree_sha,
                    "ref": self.plan.ref,
                },
            }
        return {
            "operation_class": "GITHUB_CREATE_COMMIT_PR_V1",
            "target_fingerprint": "sha256:"
            + canonical_sha256(
                {"repository": DEMO_REPOSITORY, "repository_id": DEMO_REPOSITORY_ID}
            ),
            "expected_target_revision": "git-" + self.plan.base_sha,
            "payload": {
                "schema": "aioa.github-remote-operation.v1",
                "repository_id": DEMO_REPOSITORY_ID,
                "principal_session_id": session_id,
                "policy_epoch": epoch,
                "mode": self.mode,
                "plan": self.plan.payload(),
                "plan_digest": self.plan.digest,
                "tree_sha": self.tree.sha,
                "commit_sha": self.plan.commit_sha_for_tree(self.tree.sha),
            },
        }

    def validate(self, tx, warrant, operation, *, consumed=False):
        if self.mode == "LOCAL_PATCH_FIXTURE":
            self._prospective_local()
            core_require(
                operation
                == self.operation(
                    tx.context.principal.actor_session_id, warrant.lease_epoch
                ),
                "GIT_OPERATION_SWAP",
            )
            self._local_warrant(warrant, operation)
            self._local_proofs(tx)
        core_require(
            operation
            == self.operation(
                tx.context.principal.actor_session_id, warrant.lease_epoch
            )
            and warrant.decision_dependency_root == self.dependency_root,
            "GITHUB_WARRANT_BINDING_MISMATCH",
        )
        core_require(
            (warrant.expires_at - warrant.issued_at).total_seconds() <= 300,
            "GITHUB_WARRANT_WINDOW_DENIED",
        )
        governor = self.journal.governor
        state = governor._load(tx)
        governor._epoch(state, warrant.lease_epoch)
        core_require(not state["kill"], "KILL_SWITCH")
        self.journal.ledger.require_active_in_transaction(
            tx, warrant, consumed=consumed
        )

    def _save(self, tx, key, data):
        from runtime.memory_patch.audit import append_domain_event
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.idempotency import OperationBinding
        from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord

        prior = tx.get(RecordKind.OPERATION, key)
        row = StoredRecord(
            RecordKind.OPERATION,
            key,
            self.scope,
            prior.revision + 1 if prior else 1,
            data,
        )
        if prior:
            tx.replace(row, expected_revision=prior.revision)
        else:
            tx.insert(row)
        identity = canonical_sha256([key, row.revision])
        operation = OperationBinding.bind(
            "github-op-" + identity,
            "GITHUB_CORE_RECORD",
            {"record_digest": row.payload_digest, "plan_digest": self.plan.digest},
        )
        append_domain_event(
            tx,
            operation,
            event_id="github-audit-" + identity,
            proof_id="github-outbox-" + identity,
            resource_id=key,
            before=prior.payload["state"] if prior else None,
            after=data["state"],
            content_digest=row.payload_digest,
            at=self.journal.ledger.clock(),
        )
        return row

    def begin_step(self, principal, warrant, operation, step, digest):
        from runtime.core_admission import Capability
        from runtime.mcp_bridge.github_remote import PREFIX
        from runtime.memory_patch.persistence.ports import RecordKind

        p = self.plan
        expected = {
            "tree": (
                "/git/trees",
                {
                    "base_tree": self.base.sha,
                    "tree": [
                        {
                            "path": path,
                            "mode": "100644",
                            "type": "blob",
                            "content": data.decode(),
                        }
                        for path, data in p.files.items()
                    ],
                },
            ),
            "commit": ("/git/commits", p.commit_payload(self.tree.sha)),
            "branch": (
                "/git/refs",
                {
                    "ref": "refs/heads/" + p.branch,
                    "sha": p.commit_sha_for_tree(self.tree.sha),
                },
            ),
            "draft_pr": (
                "/pulls",
                {
                    "title": p.title,
                    "body": p.body,
                    "head": p.branch,
                    "base": "main",
                    "draft": True,
                    "maintainer_can_modify": False,
                },
            ),
        }
        core_require(
            step in expected
            and digest
            == sha256(
                canonical(
                    {
                        "method": "POST",
                        "path": PREFIX + expected[step][0],
                        "payload": expected[step][1],
                    }
                )
            ),
            "GITHUB_STEP_BINDING_MISMATCH",
        )
        key = "github-step-" + p.operation_id + "-" + step

        def start(tx):
            self.validate(tx, warrant, operation, consumed=True)
            _, intent = self.journal._load(tx, warrant)
            core_require(
                intent is not None and intent["resolution"] is None,
                "GITHUB_INTENT_REQUIRED",
            )
            if tx.get(RecordKind.OPERATION, key) is not None:
                return False
            earlier = list(expected)[: list(expected).index(step)]
            core_require(
                all(
                    tx.get(
                        RecordKind.OPERATION, "github-step-" + p.operation_id + "-" + s
                    )
                    is not None
                    for s in earlier
                ),
                "GITHUB_STEP_ORDER_DENIED",
            )
            self._save(
                tx,
                key,
                {
                    "schema": "aioa.github-step.v1",
                    "state": "GITHUB_STEP_UNKNOWN",
                    "step": step,
                    "request_digest": digest,
                    "warrant_digest": warrant.digest(),
                    "operation_hash": warrant.operation_hash,
                    "automatic_retry": False,
                },
            )
            return True

        return self.journal._run(principal, Capability.COMMIT, start)

    def bind_api(self, check, cancel):
        from runtime.mcp_bridge.github_remote import GitHubCreateOnly

        api = self.api_factory(check, cancel)
        core_require(
            type(api) is GitHubCreateOnly
            and api.plan == self.plan
            and api.base == self.base
            and api.mode == self.mode
            and (
                api._transport is None
                if self.mode == "LIVE"
                else callable(api._transport)
            ),
            "GITHUB_REGISTERED_EXECUTOR_REQUIRED",
        )
        return api

    def record_credential_scope(self, principal, warrant, operation, api):
        from runtime.core_admission import Capability

        evidence = api.credential.evidence()

        def save(tx):
            self.validate(tx, warrant, operation, consumed=True)
            _, intent = self.journal._load(tx, warrant)
            core_require(
                intent is not None and intent["resolution"] is None,
                "GITHUB_INTENT_REQUIRED",
            )
            self._save(
                tx,
                "github-auth-" + self.plan.operation_id,
                {
                    "state": "GITHUB_SCOPE_VERIFIED",
                    "warrant_digest": warrant.digest(),
                    "operation_hash": warrant.operation_hash,
                    "evidence": evidence,
                },
            )

        self.journal._run(principal, Capability.COMMIT, save)

    def result(self, principal):
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import RecordKind

        def read(tx):
            row = tx.get(
                RecordKind.OPERATION, "github-result-" + self.plan.operation_id
            )
            return (
                json.loads(canonical_json_bytes(row.payload))["result"] if row else None
            )

        return self.journal._run(principal, Capability.READ, read)

    def complete(self, principal, warrant, observation, *, historical=False):
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.outcome import Applied
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.liability import Reconciliation
        from runtime.mobile_gateway.wire import canonical as wire_canonical

        core_require(
            observation["plan_digest"] == self.plan.digest
            and observation["mode"]
            in (
                ("LIVE", "PUBLIC_READ_ONLY")
                if self.mode == "LIVE"
                else ("OFFLINE_FIXTURE",)
            ),
            "GITHUB_READBACK_BINDING_MISMATCH",
        )
        terminal = observation["remote_effect_verified"] is True
        receipt = {
            "schema": "aioa.github-write-receipt.v1",
            "operation_id": self.plan.operation_id,
            "plan_digest": self.plan.digest,
            "warrant_digest": warrant.digest(),
            "operation_hash": warrant.operation_hash,
            "source_reply_sha256": self.plan.source_reply_sha256,
            "source_receipt_sha256": self.plan.source_receipt_sha256,
            "source_sha": self.plan.source_sha,
            "capsule_digest": self.plan.capsule_digest,
            "observed_at": int(self.journal.ledger.clock().timestamp()),
            "mode": self.mode,
            "live_verified": self.mode == "LIVE" and terminal,
            "commit_sha": observation.get("commit_sha"),
            "github_url": observation.get("commit_url"),
            "pr_url": observation.get("pr_url"),
            "state": "CODE_COMMITTED_AND_DRAFT_PR_CREATED"
            if self.mode == "LIVE" and terminal
            else "OFFLINE_PROTOCOL_VERIFIED"
            if terminal
            else "UNKNOWN",
            "readback_sha256": canonical_sha256(observation),
            "automatic_retry": False,
        }
        scope_key = "github-auth-" + self.plan.operation_id
        scope = self.journal._run(
            principal,
            Capability.COMMIT,
            lambda tx: tx.get(RecordKind.OPERATION, scope_key),
        )
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes

        if terminal:
            core_require(
                scope is not None
                and scope.payload["warrant_digest"] == warrant.digest()
                and scope.payload["operation_hash"] == warrant.operation_hash,
                "GITHUB_SCOPE_PROVENANCE_REQUIRED",
            )
        signed = {
            **receipt,
            "credential_scope": json.loads(
                canonical_json_bytes(scope.payload["evidence"])
            )
            if scope
            else None,
        }
        # Signing randomness stays outside the retryable transaction callback.
        result = {
            "observation": observation,
            "receipt": signed,
            "signature": self.identity.sign(signed),
            "receipt_sha256": sha256(wire_canonical(signed)),
        }

        def save(tx):
            _, intent = self.journal._load(tx, warrant)
            core_require(
                intent is not None
                and intent["operation"]["payload"]["plan_digest"] == self.plan.digest,
                "GITHUB_INTENT_REQUIRED",
            )
            if intent["resolution"] is not None:
                return self.journal._public(intent)
            if not historical:
                self.validate(tx, warrant, intent["operation"], consumed=True)
            current_scope = tx.get(RecordKind.OPERATION, scope_key)
            core_require(
                (current_scope.payload_digest if current_scope else None)
                == (scope.payload_digest if scope else None),
                "GITHUB_SCOPE_PROVENANCE_CHANGED",
            )
            if terminal:
                for step in ("tree", "commit", "branch", "draft_pr"):
                    key = "github-step-" + self.plan.operation_id + "-" + step
                    row = tx.get(RecordKind.OPERATION, key)
                    core_require(
                        row is not None
                        and row.payload.get("warrant_digest") == warrant.digest()
                        and row.payload.get("operation_hash") == warrant.operation_hash,
                        "GITHUB_AIOA_DISPATCH_PROVENANCE_REQUIRED",
                    )
                    data = json.loads(canonical_json_bytes(row.payload))
                    self._save(
                        tx,
                        key,
                        {
                            **data,
                            "state": "GITHUB_STEP_VERIFIED",
                            "readback_sha256": canonical_sha256(observation),
                        },
                    )
            self._save(
                tx,
                "github-result-" + self.plan.operation_id,
                {
                    "schema": "aioa.github-result.v1",
                    "state": "GITHUB_VERIFIED" if terminal else "GITHUB_UNKNOWN",
                    "result": result,
                },
            )
            if not terminal:
                return self.journal._public(intent)
            proof = EvidenceRef(
                "github-receipt-" + self.plan.operation_id,
                "receipt",
                "sha256:" + canonical_sha256(result),
                "v1",
            )
            read = EvidenceRef(
                "github-get-" + self.plan.operation_id,
                "independent-readback",
                "sha256:" + canonical_sha256(observation),
                "v1",
            )
            resolution = Reconciliation(
                warrant.operation_hash, Applied(proof.evidence_id), proof, read
            )
            epoch = self.journal.governor._load(tx)["epoch"]
            return self.journal.apply_resolution_in_transaction(
                tx, warrant, epoch, resolution
            )

        return self.journal._run(principal, Capability.COMMIT, save)

    def dispatch(self, principal, warrant, operation, reservation, *, cancel):
        from runtime.service_guard.service import CoreServiceGuard

        if self.mode == "LOCAL_PATCH_FIXTURE":
            self._prospective_local()
        return CoreServiceGuard.dispatch_registered_remote_git(
            self, principal, warrant, operation, reservation, cancel=cancel
        )

    def reconcile(self, principal, warrant, *, cancel, api=None):
        from runtime.core_admission import Capability
        from runtime.mcp_bridge.github_remote import GitHubCreateOnly

        self.core.require(principal, Capability.COMMIT, scope=self.scope)
        with self.target_guard():
            if self.mode == "LOCAL_PATCH_FIXTURE":
                self.owner_check()
                core_require(
                    not cancel.cancelled and api is None, "GIT_RECONCILE_BINDING"
                )
                _, intent = self.journal._run(
                    principal,
                    Capability.COMMIT,
                    lambda tx: self.journal._load(tx, warrant),
                )
                core_require(intent is not None, "GIT_INTENT_REQUIRED")
                return self._complete_local_patch(principal, warrant, historical=True)
            self.check()
            if self.mode == "LIVE":
                core_require(api is None, "GITHUB_READBACK_INJECTION_DENIED")
                api = GitHubCreateOnly(
                    self.plan, self.base, None, mode="PUBLIC_READ_ONLY"
                )
            core_require(
                type(api) is GitHubCreateOnly
                and api.plan == self.plan
                and api.base == self.base
                and api.mode
                == ("PUBLIC_READ_ONLY" if self.mode == "LIVE" else "OFFLINE_FIXTURE"),
                "GITHUB_READBACK_BINDING_MISMATCH",
            )
            # Existing intent is required before any recovery GET. No active
            # warrant/old owner session is resurrected after restart or expiry.
            _, intent = self.journal._run(
                principal, Capability.COMMIT, lambda tx: self.journal._load(tx, warrant)
            )
            core_require(
                intent is not None
                and intent["operation"]["payload"]["plan_digest"] == self.plan.digest,
                "GITHUB_INTENT_REQUIRED",
            )
            observation = api.readback(check=self.check, cancel=cancel)
            self.check()
            return self.complete(principal, warrant, observation, historical=True)


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedPatchSet:
    """Bounded postimages for review, with no authority or default transport.

    MODIFY/DELETE require a separately qualified versioned actuator profile.
    The existing production create-only profile is deliberately unchanged.
    """

    patchset: object
    postimages: tuple
    capsule_digest: str
    preimages: tuple = ()

    def __post_init__(self):
        from runtime.mission.patchset import (
            PatchSet,
            _counts,
            _diff,
            _protected_change,
            _secret_path,
            _text,
            _TreeFile,
        )

        core_require(type(self.patchset) is PatchSet, "GIT_PATCHSET_REQUIRED")
        self.patchset.verify_digest()
        core_require(
            type(self.capsule_digest) is str
            and re.fullmatch("[a-f0-9]{64}", self.capsule_digest),
            "GIT_CAPSULE_BINDING",
        )
        core_require(
            type(self.postimages) is tuple
            and len(self.postimages) == len(self.patchset.files)
            and all(type(row) is tuple and len(row) == 2 for row in self.postimages),
            "GIT_PATCH_POSTIMAGES",
        )
        core_require(
            tuple(row[0] for row in self.postimages)
            == tuple(c.path for c in self.patchset.files),
            "GIT_PATCH_POSTIMAGES",
        )
        if not self.preimages and all(
            c.operation == "ADD" for c in self.patchset.files
        ):
            before = {c.path: None for c in self.patchset.files}
        else:
            core_require(
                type(self.preimages) is tuple
                and len(self.preimages) == len(self.patchset.files)
                and all(type(row) is tuple and len(row) == 2 for row in self.preimages)
                and tuple(row[0] for row in self.preimages)
                == tuple(c.path for c in self.patchset.files),
                "GIT_PATCH_PREIMAGES",
            )
            before = dict(self.preimages)
        rendered = []
        for change, (_, data) in zip(self.patchset.files, self.postimages):
            _secret_path(change.path)
            _protected_change(change.path)
            prior = before[change.path]
            if change.before is None:
                core_require(prior is None, "GIT_PATCH_PREIMAGES")
            else:
                core_require(
                    type(prior) is bytes
                    and sha256(prior) == change.before.sha256
                    and len(prior) == change.before.size,
                    "GIT_PATCH_PREIMAGES",
                )
            if change.operation == "DELETE":
                core_require(data is None, "GIT_PATCH_POSTIMAGES")
            else:
                core_require(
                    type(data) is bytes
                    and sha256(data) == change.after.sha256
                    and len(data) == change.after.size,
                    "GIT_PATCH_POSTIMAGES",
                )
            core_require(
                change.after is None or not change.after.mode & 0o111, "GIT_PATCH_MODE"
            )
            core_require(
                change.before is None
                or change.after is None
                or change.before.mode == change.after.mode,
                "GIT_PATCH_MODE",
            )
            left = None if prior is None else _TreeFile(change.before, prior)
            right = None if data is None else _TreeFile(change.after, data)
            a, b = _text(left), _text(right)
            core_require(
                _counts(a, b) == (change.lines_added, change.lines_deleted),
                "GIT_PATCH_LINE_BINDING",
            )
            rendered.append(_diff(change.path, left, right, a, b))
        core_require(
            "".join(rendered) == self.patchset.canonical_diff, "GIT_PATCH_DIFF_BINDING"
        )

    @property
    def authority(self):
        return "NONE"

    @property
    def digest(self):
        return sha256(
            canonical(
                {
                    "patchset": self.patchset.patchset_sha256,
                    "capsule": self.capsule_digest,
                    "postimages": [
                        [path, None if data is None else sha256(data)]
                        for path, data in self.postimages
                    ],
                }
            )
        )

    def preview(self):
        self.__post_init__()
        return {
            "schema": "aioa.verified-patch-preparation.v1",
            "preparation_digest": self.digest,
            "patchset_sha256": self.patchset.patchset_sha256,
            "capsule_digest": self.capsule_digest,
            "source_base_sha": self.patchset.source_base_sha,
            "postimage_tree_sha256": self.patchset.final_tree_sha256,
            "operations": [change.operation for change in self.patchset.files],
            "authority": "NONE",
            "live_enabled": False,
            "dispatch_registered": False,
            "required_gate": "VERSIONED_MODIFY_ACTUATOR_QUALIFICATION",
        }

    def create_only_plan(
        self,
        *,
        title,
        body,
        operation_id,
        issued_at,
        base_tree_sha,
        source_reply_sha256,
        source_receipt_sha256,
    ):
        self.__post_init__()
        # Even ADD requires a separately qualified canonical capsule-to-route
        # join. A self-consistent DTO and a digest string cannot provide it.
        core_require(False, "GITHUB_PATCH_CONVERSION_NOT_QUALIFIED")


def _bounded_git(
    repository, arguments, *, data=None, cancel=None, expected_target_identity=None
):
    """Pinned locator delegated to the existing broker's fixed offline profile."""
    import os

    from runtime.mission.sandbox_linux import LinuxSandboxBroker

    repository = Path(repository)
    core_require(
        repository.is_absolute() and repository.resolve(strict=True) == repository,
        "GIT_REPOSITORY_LOCATOR_DENIED",
    )
    root = os.open(
        repository, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        pinned = os.fstat(root)
        storage = None

        def binding_check():
            current = repository.stat()
            core_require(
                (current.st_dev, current.st_ino) == (pinned.st_dev, pinned.st_ino),
                "GIT_TARGET_MOVED",
            )
            if expected_target_identity is not None:
                identity, _ = _git_target_identity_fd(root, repository)
                core_require(identity == expected_target_identity, "GIT_TARGET_MOVED")

        if expected_target_identity is not None:
            identity, storage = _git_target_identity_fd(root, repository)
            core_require(identity == expected_target_identity, "GIT_TARGET_MOVED")
        binding_check()
        output = LinuxSandboxBroker._git_plumbing(
            root,
            arguments,
            git_sha256=LOCAL_GIT_SHA256,
            data=data,
            cancel=cancel,
            expected_storage=storage,
            binding_check=binding_check,
        )
        current = repository.stat()
        core_require(
            (pinned.st_dev, pinned.st_ino) == (current.st_dev, current.st_ino),
            "GIT_REPOSITORY_MOVED",
        )
        return output
    finally:
        os.close(root)


@dataclass(frozen=True, slots=True, repr=False)
class GitSourceSnapshot:
    """Host-observed exact Git objects, not a worker-declared SHA or authority."""

    repository_id: str
    workspace_id: str
    source_base_sha: str
    git_tree_sha: str
    files: tuple
    ref: str = "refs/heads/main"

    def __post_init__(self):
        from runtime.mission.contracts import logical_id
        from runtime.mission.patchset import _secret_path, normalize_patch_relative_path
        from runtime.nonzero_cloudops.models.redaction import (
            contains_sensitive_material,
        )

        logical_id(self.repository_id)
        logical_id(self.workspace_id)
        for value in (self.source_base_sha, self.git_tree_sha):
            core_require(
                type(value) is str and re.fullmatch("[a-f0-9]{40}", value),
                "GIT_SOURCE_IDENTITY",
            )
        core_require(
            type(self.ref) is str
            and re.fullmatch(r"refs/heads/[A-Za-z0-9][A-Za-z0-9/_-]{0,127}", self.ref),
            "GIT_SOURCE_REF",
        )
        core_require(
            type(self.files) is tuple and 0 < len(self.files) <= 256,
            "GIT_SOURCE_BOUNDS",
        )
        names = []
        total = 0
        for row in self.files:
            core_require(type(row) is tuple and len(row) == 2, "GIT_SOURCE_SCHEMA")
            path, data = row
            normalize_patch_relative_path(path)
            _secret_path(path)
            core_require(
                type(data) is bytes and len(data) <= 1048576 and b"\0" not in data,
                "GIT_SOURCE_TEXT_ONLY",
            )
            text = data.decode("utf-8")
            core_require(not contains_sensitive_material(text), "GIT_SOURCE_SENSITIVE")
            names.append(path)
            total += len(data)
        core_require(
            names == sorted(set(names))
            and len({p.casefold() for p in names}) == len(names)
            and total <= 1048576,
            "GIT_SOURCE_BOUNDS",
        )

    @property
    def digest(self):
        return sha256(
            canonical(
                {
                    "repository_id": self.repository_id,
                    "workspace_id": self.workspace_id,
                    "source_base_sha": self.source_base_sha,
                    "git_tree_sha": self.git_tree_sha,
                    "ref": self.ref,
                    "files": [[p, sha256(d)] for p, d in self.files],
                }
            )
        )

    @classmethod
    def capture(
        cls,
        repository,
        *,
        expected_sha,
        repository_id,
        workspace_id,
        ref="refs/heads/main",
        expected_target_identity=None,
    ):
        from runtime.mission.patchset import _secret_path, normalize_patch_relative_path

        core_require(
            type(expected_sha) is str and re.fullmatch("[a-f0-9]{40}", expected_sha),
            "GIT_SOURCE_IDENTITY",
        )
        core_require(
            type(ref) is str
            and re.fullmatch(r"refs/heads/[A-Za-z0-9][A-Za-z0-9/_-]{0,127}", ref),
            "GIT_SOURCE_REF",
        )

        def git(arguments):
            return _bounded_git(
                repository, arguments, expected_target_identity=expected_target_identity
            )

        core_require(
            git(("rev-parse", "--is-bare-repository")).strip() == b"true",
            "GIT_BARE_SOURCE_REQUIRED",
        )

        def current():
            return git(("rev-parse", "--verify", ref)).decode().strip()

        core_require(current() == expected_sha, "GIT_SOURCE_DRIFT")
        commit = git(("cat-file", "commit", expected_sha))
        core_require(
            git_object("commit", commit) == expected_sha, "GIT_SOURCE_COMMIT_HASH"
        )
        first = commit.splitlines()[0].decode().split()
        core_require(
            len(first) == 2
            and first[0] == "tree"
            and re.fullmatch("[a-f0-9]{40}", first[1]),
            "GIT_SOURCE_COMMIT_SCHEMA",
        )
        tree_sha = first[1]
        raw = git(("ls-tree", "-r", "-t", "-z", tree_sha))
        entries = {}
        files = []
        total_bytes = 0
        for record in raw.split(b"\0"):
            if not record:
                continue
            core_require(len(entries) < 1024, "GIT_SOURCE_BOUNDS")
            metadata, name = record.split(b"\t", 1)
            mode, kind, object_id = metadata.decode().split()
            path = normalize_patch_relative_path(name.decode("utf-8"))
            _secret_path(path)
            core_require(path not in entries, "GIT_SOURCE_DUPLICATE")
            entries[path] = (mode, kind, object_id)
            if kind == "tree":
                core_require(mode == "040000", "GIT_SOURCE_MODE")
                continue
            core_require((mode, kind) == ("100644", "blob"), "GIT_SOURCE_MODE")
            size = int(git(("cat-file", "-s", object_id)).strip())
            core_require(
                0 <= size <= 1048576
                and total_bytes + size <= 1048576
                and len(files) < 256,
                "GIT_SOURCE_BOUNDS",
            )
            blob = git(("cat-file", "blob", object_id))
            core_require(
                len(blob) == size and git_object("blob", blob) == object_id,
                "GIT_SOURCE_BLOB_HASH",
            )
            files.append((path, blob))
            total_bytes += size
        GitTreeSnapshot(tree_sha, entries)
        core_require(current() == expected_sha, "GIT_SOURCE_DRIFT")
        return cls(
            repository_id,
            workspace_id,
            expected_sha,
            tree_sha,
            tuple(sorted(files)),
            ref,
        )

    def verify(self, repository):
        observed = type(self).capture(
            repository,
            expected_sha=self.source_base_sha,
            repository_id=self.repository_id,
            workspace_id=self.workspace_id,
            ref=self.ref,
        )
        core_require(observed == self, "GIT_SOURCE_DRIFT")
        return self.digest

    @property
    def export_tree_sha256(self):
        from runtime.memory_patch.contracts.serialization import canonical_sha256

        return canonical_sha256([[p, sha256(d), len(d), 0o644] for p, d in self.files])

    def verify_export(self, root):
        from runtime.mission.patchset import _snapshot

        core_require(
            _snapshot(Path(root)).digest == self.export_tree_sha256,
            "GIT_SOURCE_EXPORT_DRIFT",
        )
        return self.export_tree_sha256

    def export(self, root):
        from runtime.mission.patchset import observe_source

        root = Path(root)
        core_require(root.is_absolute() and not root.exists(), "GIT_EXPORT_FRESH_ROOT")
        from runtime.mission.patchset import _export_fresh_tree

        _export_fresh_tree(
            root, tuple((path, data, 0o644) for path, data in self.files)
        )
        self.verify_export(root)
        return observe_source(
            root,
            repository_id=self.repository_id,
            workspace_id=self.workspace_id,
            source_base_sha=self.source_base_sha,
        )


def _git_target_identity_fd(fd, repository):
    """Marker and storage proof for THIS opened FD, never a second path open."""
    import os
    import stat

    from runtime.mission.sandbox_linux import git_storage_identity

    info = os.fstat(fd)
    storage = git_storage_identity(fd)
    try:
        marker = os.open(
            ".aioa-disposable-bare",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOATIME | os.O_CLOEXEC,
            dir_fd=fd,
        )
    except FileNotFoundError:
        raise ValueError("GIT_DISPOSABLE_MARKER_REQUIRED") from None
    try:
        before = os.fstat(marker)
        core_require(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == os.getuid()
            and before.st_nlink == 1
            and not before.st_mode & 0o7077
            and before.st_size == len(b"AIOA_DISPOSABLE_BARE_PATCH_V1\n"),
            "GIT_DISPOSABLE_MARKER_REQUIRED",
        )
        core_require(
            os.pread(marker, 128, 0) == b"AIOA_DISPOSABLE_BARE_PATCH_V1\n",
            "GIT_DISPOSABLE_MARKER_REQUIRED",
        )
        after = os.fstat(marker)
        named = os.stat(".aioa-disposable-bare", dir_fd=fd, follow_symlinks=False)
        identity = lambda row: (
            row.st_dev,
            row.st_ino,
            row.st_nlink,
            row.st_size,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )
        core_require(
            identity(before) == identity(after) == identity(named), "GIT_TARGET_MOVED"
        )
    finally:
        os.close(marker)
    return (
        info.st_dev,
        info.st_ino,
        sha256(canonical([str(repository), storage])),
    ), storage


def _git_target_identity(repository):
    import os

    root = Path(repository)
    core_require(
        root.is_absolute() and root.resolve(strict=True) == root, "GIT_TARGET_LOCATOR"
    )
    fd = os.open(
        root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NOATIME | os.O_CLOEXEC
    )
    try:
        identity, _ = _git_target_identity_fd(fd, root)
        current = root.stat()
        core_require(
            identity[:2] == (current.st_dev, current.st_ino), "GIT_TARGET_MOVED"
        )
        return identity
    finally:
        os.close(fd)


@dataclass(frozen=True, slots=True, repr=False)
class LocalPatchGitPlan:
    """Pure deterministic commit data; only the registered route may execute it."""

    source: GitSourceSnapshot
    preparation: VerifiedPatchSet
    profile_digest: str
    target_identity: tuple
    issued_at: int

    def __post_init__(self):
        core_require(
            type(self.source) is GitSourceSnapshot
            and type(self.preparation) is VerifiedPatchSet,
            "GIT_LOCAL_PLAN_CONTRACT",
        )
        self.preparation.__post_init__()
        core_require(
            self.preparation.patchset.base_tree_sha256
            == self.source.export_tree_sha256,
            "GIT_SOURCE_PATCH_BINDING",
        )
        before = dict(self.source.files)
        for name, data in self.preparation.preimages:
            core_require(before.get(name) == data, "GIT_SOURCE_PREIMAGE_BINDING")
        from runtime.memory_patch.contracts.serialization import canonical_sha256

        core_require(
            canonical_sha256(
                [[name, sha256(data), len(data), 0o644] for name, data in self.files]
            )
            == self.preparation.patchset.final_tree_sha256,
            "GIT_FINAL_TREE_BINDING",
        )
        core_require(
            type(self.target_identity) is tuple
            and len(self.target_identity) == 3
            and type(self.issued_at) is int
            and self.issued_at > 0,
            "GIT_LOCAL_PLAN_CONTRACT",
        )

    @property
    def files(self):
        result = dict(self.source.files)
        for name, data in self.preparation.postimages:
            if data is None:
                del result[name]
            else:
                result[name] = data
        return tuple(sorted(result.items()))

    @property
    def operation_id(self):
        return self.preparation.capsule_digest[:32]

    @property
    def ref(self):
        return "refs/heads/aioa/nz11-" + self.operation_id

    @property
    def target_fingerprint(self):
        return "sha256:" + sha256(
            canonical(
                {
                    "repository_id": self.source.repository_id,
                    "target_identity": self.target_identity,
                    "profile": "DISPOSABLE_BARE_PATCH_V1",
                }
            )
        )

    @property
    def tree_objects(self):
        groups = {"": {}}
        for name, data in self.files:
            parent, _, leaf = name.rpartition("/")
            groups.setdefault(parent, {})[leaf] = ("100644", git_object("blob", data))
            while parent:
                upper, _, part = parent.rpartition("/")
                groups.setdefault(upper, {})[part] = ("40000", parent)
                parent = upper
        objects = []
        hashes = {}
        for directory in sorted(
            groups, key=lambda p: len(p.split("/")) if p else 0, reverse=True
        ):
            rows = groups[directory]
            raw = b"".join(
                mode.encode()
                + b" "
                + name.encode()
                + b"\0"
                + bytes.fromhex(hashes[value] if mode == "40000" else value)
                for name, (mode, value) in sorted(
                    rows.items(),
                    key=lambda row: (
                        row[0].encode() + (b"/" if row[1][0] == "40000" else b"\0")
                    ),
                )
            )
            hashes[directory] = git_object("tree", raw)
            objects.append(("tree", raw, hashes[directory]))
        return tuple(objects)

    @property
    def tree_sha(self):
        return self.tree_objects[-1][2]

    @property
    def commit_data(self):
        actor = (
            b"AIOA Core <aioa-core@aioa.invalid> "
            + str(self.issued_at).encode()
            + b" +0000"
        )
        return (
            b"tree "
            + self.tree_sha.encode()
            + b"\nparent "
            + self.source.source_base_sha.encode()
            + b"\nauthor "
            + actor
            + b"\ncommitter "
            + actor
            + b"\n\nAIOA approved bounded Python patch "
            + self.preparation.patchset.patchset_sha256.encode()
            + b"\n"
        )

    @property
    def commit_sha(self):
        return git_object("commit", self.commit_data)

    @property
    def objects(self):
        return (
            tuple(("blob", data, git_object("blob", data)) for _, data in self.files)
            + self.tree_objects
            + (("commit", self.commit_data, self.commit_sha),)
        )

    @property
    def digest(self):
        from runtime.mission import sandbox_linux

        return sha256(
            canonical(
                {
                    "schema": "aioa.local-patch-git-plan.v1",
                    "git_execution_profile": {
                        "schema": "aioa.fixed-git-readonly-create-only.v1",
                        "git_sha256": LOCAL_GIT_SHA256,
                        "runtime": sandbox_linux.GIT_RUNTIME_PINS,
                        "broker_sha256": sha256(
                            Path(sandbox_linux.__file__).read_bytes()
                        ),
                    },
                    "source": self.source.digest,
                    "preparation": self.preparation.digest,
                    "profile": self.profile_digest,
                    "target_fingerprint": self.target_fingerprint,
                    "ref": self.ref,
                    "tree": self.tree_sha,
                    "commit": self.commit_sha,
                }
            )
        )
