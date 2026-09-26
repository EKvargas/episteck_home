"""Strict CP -> BFF bootstrap response validator (§4).

The CP response is NEVER passed through. Every field is checked against an
explicit allowlist and a brand-new dict is constructed. A single violation
anywhere rejects the WHOLE payload — there is no partially-valid bootstrap.
"""
from __future__ import annotations

import re

from .frappe_client import UpstreamMalformed

PERSON_ID_RE = re.compile(r"^PSN-[0-9]{5,}$")
CIRCLE_ID_RE = re.compile(r"^CIR-[0-9]{5,}$")

MAX_DISPLAY_NAME_LENGTH = 140
MAX_CONTEXTS = 50

RELATIONSHIP_TYPES = frozenset(
    {"CAREGIVER", "COORDINATOR", "GUARDIAN", "FAMILY_SUPPORT"}
)

# Any Unicode "control" character, plus the C1 range, is rejected. This is a
# conservative denylist on top of the allowlist-by-construction approach: even a
# well-typed string must not carry terminal-escape or similarly hostile bytes.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _fail(reason: str) -> None:
    raise UpstreamMalformed(reason)


def _require_dict(value, reason: str) -> dict:
    if not isinstance(value, dict):
        _fail(reason)
    return value


def _require_list(value, reason: str) -> list:
    if not isinstance(value, list):
        _fail(reason)
    return value


def _validate_person_id(value, reason: str) -> str:
    if not isinstance(value, str) or not PERSON_ID_RE.fullmatch(value):
        _fail(reason)
    return value


def _validate_circle_id(value, reason: str) -> str:
    if not isinstance(value, str) or not CIRCLE_ID_RE.fullmatch(value):
        _fail(reason)
    return value


def _validate_display_name(value, reason: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(reason)
    if len(value) > MAX_DISPLAY_NAME_LENGTH:
        _fail(reason)
    if _CONTROL_CHAR_RE.search(value):
        _fail(reason)
    return value


def validate_bootstrap_response(raw: dict) -> dict:
    """Validate `raw` (the CP's `get_home_bootstrap` message body) and return
    the BFF wire-v1 shape (§4). Raises UpstreamMalformed on any violation.
    """
    raw = _require_dict(raw, "bootstrap response is not an object")

    viewer_raw = _require_dict(raw.get("viewer"), "viewer is missing or not an object")
    viewer_id = _validate_person_id(
        viewer_raw.get("person_id"), "viewer.person_id is malformed"
    )
    viewer_name = _validate_display_name(
        viewer_raw.get("display_name"), "viewer.display_name is malformed"
    )

    circles_raw = _require_list(raw.get("circles"), "circles is missing or not a list")
    if len(circles_raw) > MAX_CONTEXTS:
        _fail("circles exceeds the maximum bound")

    circle_contexts = []
    seen_circle_ids: set[str] = set()
    for entry in circles_raw:
        entry = _require_dict(entry, "a circle entry is not an object")
        circle_id = _validate_circle_id(
            entry.get("circle_id"), "circle.circle_id is malformed"
        )
        display_name = _validate_display_name(
            entry.get("display_name"), "circle.display_name is malformed"
        )
        if circle_id in seen_circle_ids:
            _fail("duplicate circle context")
        seen_circle_ids.add(circle_id)
        circle_contexts.append(
            {"type": "CIRCLE", "circleId": circle_id, "displayName": display_name}
        )

    care_raw = _require_list(raw.get("care"), "care is missing or not a list")
    if len(care_raw) > MAX_CONTEXTS:
        _fail("care exceeds the maximum bound")

    person_contexts = [
        {"type": "PERSON", "personId": viewer_id, "displayName": viewer_name}
    ]
    care_relationships = []
    seen_subject_ids: set[str] = set()

    for entry in care_raw:
        entry = _require_dict(entry, "a care entry is not an object")
        subject_id = _validate_person_id(
            entry.get("person_id"), "care.person_id is malformed"
        )
        subject_name = _validate_display_name(
            entry.get("display_name"), "care.display_name is malformed"
        )
        relationship_type = entry.get("relationship_type")
        if not isinstance(relationship_type, str) or relationship_type not in RELATIONSHIP_TYPES:
            _fail("care.relationship_type is unknown")

        if subject_id == viewer_id:
            _fail("a care subject cannot equal the viewer")
        if subject_id in seen_subject_ids:
            _fail("duplicate care subject")
        seen_subject_ids.add(subject_id)

        person_contexts.append(
            {"type": "PERSON", "personId": subject_id, "displayName": subject_name}
        )
        care_relationships.append(
            {"subjectPersonId": subject_id, "relationshipType": relationship_type}
        )

    # Namespace collision guard: a circleId must never coincide with any personId
    # already placed in personContexts (the "PSN-00001 used as a circle id" case).
    person_ids = {ctx["personId"] for ctx in person_contexts}
    circle_ids = {ctx["circleId"] for ctx in circle_contexts}
    if person_ids & circle_ids:
        _fail("a circle id collides with a person id")

    # Every careRelationships[].subjectPersonId must exist in personContexts.
    # By construction above this always holds (care IS the source of both), but
    # the check stays explicit so a future refactor cannot silently break it.
    context_person_ids = {ctx["personId"] for ctx in person_contexts}
    for relationship in care_relationships:
        if relationship["subjectPersonId"] not in context_person_ids:
            _fail("careRelationships references an unknown personId")

    return {
        "version": 1,
        "viewer": {"personId": viewer_id, "displayName": viewer_name},
        "personContexts": person_contexts,
        "circleContexts": circle_contexts,
        "careRelationships": care_relationships,
    }
