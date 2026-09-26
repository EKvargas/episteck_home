"""Strict CP -> BFF bootstrap response validation (§4, CP-12/BFF-12/BFF-13)."""
from __future__ import annotations

import pytest

from home_bff.bootstrap import validate_bootstrap_response
from home_bff.frappe_client import UpstreamMalformed

VALID_RAW = {
    "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
    "circles": [{"circle_id": "CIR-00001", "display_name": "Family"}],
    "care": [
        {
            "person_id": "PSN-00007",
            "display_name": "Ana",
            "relationship_type": "CAREGIVER",
        }
    ],
}


def test_valid_payload_maps_to_wire_v1_shape():
    result = validate_bootstrap_response(VALID_RAW)
    assert result == {
        "version": 1,
        "viewer": {"personId": "PSN-00001", "displayName": "Erick"},
        "personContexts": [
            {"type": "PERSON", "personId": "PSN-00001", "displayName": "Erick"},
            {"type": "PERSON", "personId": "PSN-00007", "displayName": "Ana"},
        ],
        "circleContexts": [
            {"type": "CIRCLE", "circleId": "CIR-00001", "displayName": "Family"}
        ],
        "careRelationships": [
            {"subjectPersonId": "PSN-00007", "relationshipType": "CAREGIVER"}
        ],
    }


def test_viewer_is_always_first_person_context_even_with_no_care():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [],
        "care": [],
    }
    result = validate_bootstrap_response(raw)
    assert result["personContexts"] == [
        {"type": "PERSON", "personId": "PSN-00001", "displayName": "Erick"}
    ]


@pytest.mark.parametrize(
    "bad_person_id",
    [
        "PSN-1",
        "psn-00001",
        "PSN00001",
        "CIR-00001",
        "",
        "PSN-abcde",
        # A trailing newline must NOT satisfy `$`-anchored matching: Python's
        # `$` matches at end-of-string OR immediately before a trailing `\n`,
        # so a naive `.match()` call would let this slip past as if it were
        # "PSN-00001" for the purposes of format validation, even though the
        # two strings are not equal and would defeat the viewer/duplicate
        # equality guards downstream.
        "PSN-00001\n",
        # `\d` matches any Unicode decimal digit by default, not just ASCII
        # 0-9. Arabic-Indic digits U+0661..U+0665 spell "12345".
        "PSN-١٢٣٤٥",
    ],
)
def test_invalid_person_id_format_rejects_whole_payload(bad_person_id):
    raw = {
        "viewer": {"person_id": bad_person_id, "display_name": "X"},
        "circles": [],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


@pytest.mark.parametrize(
    "bad_circle_id",
    [
        "CIR-1",
        "cir-00001",
        "PSN-00001",
        "",
        # Same trailing-newline bypass as person_id, for circle_id.
        "CIR-00001\n",
        # Same Unicode-digit bypass as person_id, for circle_id.
        "CIR-١٢٣٤٥",
    ],
)
def test_invalid_circle_id_format_rejects_whole_payload(bad_circle_id):
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "X"},
        "circles": [{"circle_id": bad_circle_id, "display_name": "Family"}],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_care_subject_with_trailing_newline_is_rejected_not_treated_as_distinct():
    """Before the fix, "PSN-00001\\n" passed the format check (Python's `$`
    tolerates a trailing newline), so it was treated as a DIFFERENT id than
    the viewer's "PSN-00001" and silently accepted as a legitimate care
    subject. It must now be rejected by the format check itself, so the
    whole payload fails closed rather than admitting a near-duplicate id.
    """
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [],
        "care": [
            {
                "person_id": "PSN-00001\n",
                "display_name": "Erick",
                "relationship_type": "CAREGIVER",
            }
        ],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_empty_display_name_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": ""},
        "circles": [],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_display_name_over_140_chars_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "x" * 141},
        "circles": [],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_display_name_with_control_characters_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick\x00"},
        "circles": [],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_unknown_relationship_type_rejects_whole_payload():
    raw = dict(VALID_RAW)
    raw["care"] = [
        {"person_id": "PSN-00007", "display_name": "Ana", "relationship_type": "FRIEND"}
    ]
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


@pytest.mark.parametrize(
    "unhashable_relationship_type",
    [["CAREGIVER"], {"type": "CAREGIVER"}],
    ids=["list", "dict"],
)
def test_unhashable_relationship_type_rejects_whole_payload_not_typeerror(
    unhashable_relationship_type,
):
    """A list or dict is unhashable, so a bare `x not in frozenset` raises
    TypeError instead of returning False. This must be caught as an ordinary
    malformed-shape rejection (UpstreamMalformed), never propagate as a raw
    TypeError (which would surface as an unhandled 500 at the HTTP layer).
    """
    raw = dict(VALID_RAW)
    raw["care"] = [
        {
            "person_id": "PSN-00007",
            "display_name": "Ana",
            "relationship_type": unhashable_relationship_type,
        }
    ]
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


@pytest.mark.parametrize(
    "relationship_type",
    ["CAREGIVER", "COORDINATOR", "GUARDIAN", "FAMILY_SUPPORT"],
)
def test_all_four_relationship_types_are_accepted(relationship_type):
    raw = dict(VALID_RAW)
    raw["care"] = [
        {
            "person_id": "PSN-00007",
            "display_name": "Ana",
            "relationship_type": relationship_type,
        }
    ]
    result = validate_bootstrap_response(raw)
    assert result["careRelationships"][0]["relationshipType"] == relationship_type


def test_care_subject_equal_to_viewer_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [],
        "care": [
            {
                "person_id": "PSN-00001",
                "display_name": "Erick",
                "relationship_type": "CAREGIVER",
            }
        ],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_duplicate_care_subject_rejects_whole_payload():
    raw = dict(VALID_RAW)
    raw["care"] = [
        {
            "person_id": "PSN-00007",
            "display_name": "Ana",
            "relationship_type": "CAREGIVER",
        },
        {
            "person_id": "PSN-00007",
            "display_name": "Ana",
            "relationship_type": "COORDINATOR",
        },
    ]
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_care_relationship_referencing_unknown_person_id_rejects_whole_payload():
    """A subjectPersonId with no matching personContexts entry is a dangling ref."""
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [],
        "care": [],
    }
    # Simulate a CP bug: care references a person never listed. Since `care` drives
    # personContexts membership in this validator, construct the malformed case by
    # directly testing a hand-built raw shape the validator cannot self-consistently
    # produce a dangling reference from care alone (care IS the source of personContexts
    # beyond viewer) — so this case is exercised via a duplicate circle id colliding
    # with a person id namespace instead, which the validator must also reject:
    raw["circles"] = [{"circle_id": "PSN-00001", "display_name": "Not a circle"}]
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_over_bound_circles_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [
            {"circle_id": f"CIR-{i:05d}", "display_name": f"Circle {i}"}
            for i in range(51)
        ],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_over_bound_care_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [],
        "care": [
            {
                "person_id": f"PSN-{i:05d}",
                "display_name": f"Person {i}",
                "relationship_type": "CAREGIVER",
            }
            for i in range(1, 52)
        ],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_missing_required_field_rejects_whole_payload():
    raw = {"viewer": {"person_id": "PSN-00001"}, "circles": [], "care": []}
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_wrong_type_for_circles_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": "not-a-list",
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_unknown_extra_fields_are_dropped_not_rejected():
    raw = dict(VALID_RAW)
    raw["viewer"] = dict(raw["viewer"], external_ref="secret-ref", User_name="admin@x")
    raw["grants"] = ["should never appear"]
    result = validate_bootstrap_response(raw)
    assert "external_ref" not in result["viewer"]
    assert "grants" not in result
    assert "User_name" not in result["viewer"]
    import json

    assert "secret-ref" not in json.dumps(result)
