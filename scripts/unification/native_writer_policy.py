"""Render the broker's session-specific AppArmor storage rules for operator review."""

import argparse
import re

from runtime.red_hat.broker_protocol import require


def storage_rules(session, exact_ref):
    require(type(session) is str and re.fullmatch(r"[0-9a-f]{32}", session)
            and type(exact_ref) is str and re.fullmatch(r"refs/heads/aioa/nz11-[0-9a-f]{32}", exact_ref),
            "NATIVE_POLICY_SCOPE")
    root = f"/run/aioa-qualification/{session}"
    prefix = "[0-9a-f]" * 2
    oid = "[0-9a-f]" * 38
    digest_name = "[0-9a-f]" * 64
    ref = f"{root}/repo/{exact_ref}"
    # The destination goes on the left in AppArmor's link-pair grammar.
    return "\n".join((
        f"{root}/ r,",
        f"{root}/writer-policy r,",
        f"{root}/writer-launch r,",
        f"{root}/writer-process r,",
        f"{root}/writer-closed r,",
        f"{root}/writer-closed-synced r,",
        f"{root}/repo/ r,",
        f"{root}/repo/** r,",
        f"{root}/staging/ rw,",
        f"{root}/staging/** rw,",
        f"{root}/repo/objects/ rw,",
        f"{root}/repo/objects/{prefix}/ rw,",
        f"{root}/repo/objects/{prefix}/{oid} rw,",
        f"link subset {root}/repo/objects/{prefix}/{oid} -> {root}/repo/objects/{prefix}/**,",
        f"{root}/state/ rw,",
        f"{root}/state/** rwlk,",
        f"{root}/evidence/ rw,",
        f"{root}/evidence/** rw,",
        f"link subset {root}/evidence/{digest_name} -> {root}/evidence/**,",
        f"link subset {root}/evidence/completion-{digest_name} -> {root}/evidence/**,",
        f"{ref} r,",
        f"link subset {ref} -> {root}/staging/**,",
        "",
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--exact-ref", required=True)
    args = parser.parse_args()
    print(storage_rules(args.session, args.exact_ref), end="")


if __name__ == "__main__":
    main()
