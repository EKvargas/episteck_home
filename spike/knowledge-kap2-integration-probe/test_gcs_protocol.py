"""Local algorithm checks for the unrun live GCS client; no cloud access."""

from __future__ import annotations

import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("gcs_protocol", Path(__file__).with_name("gcs_protocol.py"))
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def key(self, kind: str, number: int) -> str:
        return f"test/{kind}/{number:020d}.json"

    def list_all(self, *, page_size=7, after_first_page=None):
        if after_first_page:
            after_first_page()
        return sorted(self.objects), 1

    def get(self, key: str):
        return (200, self.objects[key], None) if key in self.objects else (404, b"", None)


def test_orphan_outcome_blocks_head():
    client = FakeClient()
    client.objects[client.key("outcomes", 1)] = b"{}"
    assert module.inspect_head(client)[0] == "BROKEN"


def test_gap_before_later_slot_blocks_head():
    client = FakeClient()
    client.objects[client.key("slots", 2)] = b"{}"
    assert module.inspect_head(client)[0] == "BROKEN"


def test_pending_slot_blocks_head():
    client = FakeClient()
    client.objects[client.key("slots", 1)] = module.canonical(
        {"sequence": 1, "epoch": 1, "kind": "MUTATION", "previous": "GENESIS"}
    )
    assert module.inspect_head(client)[0] == "PENDING"
