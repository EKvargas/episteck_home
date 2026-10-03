"""Synthetic two-crossing fail-closed probes; no production authorization state."""

from __future__ import annotations

import json
from pathlib import Path

import httpx


GOOD = "https://100.71.79.33:18473/probe"
UNAVAILABLE = "https://100.71.79.33:18475/probe"
BODY = b'{"pad":"synthetic"}'


def flow(client: httpx.Client, rt1_url: str, rt2_url: str) -> dict:
    result = {"rt1_success": False, "local_read": False,
              "rt2_success": False, "context_bundle_produced": False}
    try:
        first = client.post(rt1_url, content=BODY, headers={"X-Response-Bytes": "112"})
        first.raise_for_status()
        result["rt1_success"] = True
        # Synthetic stand-in for a completed local read; never uses real data.
        result["local_read"] = True
        second = client.post(rt2_url, content=BODY, headers={"X-Response-Bytes": "112"})
        second.raise_for_status()
        result["rt2_success"] = True
        result["context_bundle_produced"] = True
    except httpx.HTTPError:
        pass
    return result


def main() -> None:
    ca = "/work/ca.pem"
    with httpx.Client(verify=ca, timeout=1.0, trust_env=False) as client:
        control = flow(client, GOOD, GOOD)
        rt1_unavailable = flow(client, UNAVAILABLE, GOOD)
        rt2_unavailable = flow(client, GOOD, UNAVAILABLE)
    with httpx.Client(verify=True, timeout=1.0, trust_env=False) as client:
        tls_failure = flow(client, GOOD, GOOD)
    rows = {
        "control": control,
        "rt1_unavailable": rt1_unavailable,
        "rt2_unavailable_after_local_read": rt2_unavailable,
        "tls_untrusted_certificate": tls_failure,
        "invalid_r13_basis": "NOT_EXERCISED: no R13 issuer/verifier in transport seam",
    }
    assert control == {"rt1_success": True, "local_read": True,
                       "rt2_success": True, "context_bundle_produced": True}
    for name in ("rt1_unavailable", "rt2_unavailable_after_local_read", "tls_untrusted_certificate"):
        assert rows[name]["context_bundle_produced"] is False
    assert rt2_unavailable["local_read"] is True
    Path("/work/failure-probes.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
