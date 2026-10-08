"""Read-only verification of a completed disposable GCS journal history."""

from __future__ import annotations

import json
import os
from pathlib import Path

from gcs_protocol import Client, inspect_head, sha, token
from journal_trust import root_fingerprint, verify_registration


def main() -> None:
    bucket = os.environ["KAP2_GCS_BUCKET"]
    run_id = os.environ["KAP2_GCS_RUN_ID"]
    prefix = f"home-auth/v1/partitions/{sha(('synthetic-' + run_id).encode())}"
    if not bucket.startswith("kap2-probe-") or len(run_id) != 32:
        raise ValueError("requires isolated synthetic bucket and run ID")
    root = Path(os.environ["KAP2_TRUST_ROOT_PEM_FILE"]).read_text(encoding="utf-8")
    if root_fingerprint(root) != os.environ["KAP2_TRUST_ROOT_SHA256"]:
        raise ValueError("independent root pin mismatch")
    first = verify_registration(
        json.loads(Path(os.environ["KAP2_SIGNED_REGISTRATION_FILE"]).read_text(encoding="utf-8")),
        root, partition=prefix, kms_version=os.environ["KAP2_KMS_SIGNER_VERSION"],
    )
    second = verify_registration(
        json.loads(Path(os.environ["KAP2_NEXT_SIGNED_REGISTRATION_FILE"]).read_text(encoding="utf-8")),
        root, partition=prefix, kms_version=os.environ["KAP2_NEXT_KMS_SIGNER_VERSION"], prior=first,
    )
    client = Client(bucket, token(os.environ["KAP2_GCS_VERIFIER_SERVICE_ACCOUNT"]), prefix)
    state, sequence, pages, elapsed_ms = inspect_head(
        client, trust={first.registration_sha256: first, second.registration_sha256: second}
    )
    if (state, sequence) != ("BROKEN", 68):
        raise RuntimeError(f"expected signed head 68 followed by corrupt slot: {state}, {sequence}")
    print(json.dumps({"probe": "read_only_existing_history", "state": state,
                      "last_verified_commit": sequence, "list_pages": pages,
                      "elapsed_ms": elapsed_ms, "object_requests": client.counts}, sort_keys=True))


if __name__ == "__main__":
    main()
