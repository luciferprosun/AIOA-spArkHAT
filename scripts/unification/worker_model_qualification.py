"""Use the existing owner socket. Each command performs exactly one local request."""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runtime.mobile_gateway.desktop import validate_existing_profile
from runtime.webapp import mobile_operator_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "approve", "readback"))
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--review-digest")
    args = parser.parse_args()
    data = {"op": "worker_model_" + args.operation}
    if args.operation == "approve":
        if not re.fullmatch(r"[a-f0-9]{64}", args.review_digest or ""):
            parser.error("approve requires the exact reviewed SHA-256")
        data["review_digest"] = args.review_digest
    elif args.review_digest:
        parser.error("only approve accepts a review digest")
    validate_existing_profile(args.state_dir)
    answer = mobile_operator_client(args.state_dir, data)
    if answer.get("ok") is not True:
        raise SystemExit("CORE_REFUSED_OR_UNKNOWN; use readback")
    print(json.dumps(answer["data"], sort_keys=True))


if __name__ == "__main__":
    main()
