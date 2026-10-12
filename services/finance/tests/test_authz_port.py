"""The Authorizer port mirrors the proposed Home H2 `authorize_batch` contract.

Any response that does not prove it decided exactly what we asked is UNAVAILABLE,
never an allow.
"""
from __future__ import annotations

import pytest

from app.authz import (
    ANSWERED, MAX_REQUIREMENTS, SELF, SESSION_INVALID, UNAVAILABLE, Requirement,
    validate_batch,
)

SENT = (Requirement(SELF, "VIEW"), Requirement("PSN-2", "VIEW"))


def _response(**over):
    body = {
        "actor_person_id": "PSN-1",
        "decisions": [
            {"subject": "SELF", "domain": "FINANCE", "action": "VIEW", "allow": True, "reason": "ok"},
            {"subject": "PSN-2", "domain": "FINANCE", "action": "VIEW", "allow": False, "reason": "no grant"},
        ],
    }
    body.update(over)
    return body


def test_well_formed_answer_exposes_actor_and_positional_decisions():
    result = validate_batch(SENT, _response())
    assert result.outcome == ANSWERED
    assert result.actor_person_id == "PSN-1"
    assert [d.allow for d in result.decisions] == [True, False]
    assert result.is_allowed(SELF) is True
    assert result.is_allowed("PSN-2") is False
    assert result.is_allowed("PSN-404") is False  # never asked: not allowed


def test_extra_top_level_fields_are_ignored():
    assert validate_batch(SENT, _response(extra="x")).outcome == ANSWERED


@pytest.mark.parametrize("mutate", [
    lambda b: b["decisions"].pop(),                                   # too few
    lambda b: b["decisions"].append(dict(b["decisions"][0])),         # too many
    lambda b: b["decisions"].reverse(),                               # reordered
    lambda b: b["decisions"][0].update(action="CREATE"),              # wrong action
    lambda b: b["decisions"][0].update(domain="NUTRITION"),           # wrong domain
    lambda b: b["decisions"][0].update(subject="PSN-9"),              # wrong subject
    lambda b: b["decisions"][0].update(allow="true"),                 # not a real bool
    lambda b: b["decisions"][0].update(allow=1),                      # truthy int
    lambda b: b["decisions"][0].update(reason=""),                    # empty reason
    lambda b: b["decisions"][0].pop("reason"),                        # missing reason
    lambda b: b.update(actor_person_id=""),                           # no actor
    lambda b: b.pop("actor_person_id"),
    lambda b: b.update(decisions="nope"),
    lambda b: b["decisions"].__setitem__(0, "not-a-dict"),
])
def test_any_malformed_or_mismatched_answer_is_unavailable(mutate):
    body = _response()
    mutate(body)
    assert validate_batch(SENT, body).outcome == UNAVAILABLE


def test_non_dict_payload_is_unavailable():
    assert validate_batch(SENT, None).outcome == UNAVAILABLE  # type: ignore[arg-type]
    assert validate_batch(SENT, []).outcome == UNAVAILABLE  # type: ignore[arg-type]


def test_a_denied_answer_never_reads_as_allowed():
    body = _response()
    body["decisions"][0]["allow"] = False
    assert validate_batch(SENT, body).is_allowed(SELF) is False


def test_requirement_limits_are_enforced_before_any_call():
    with pytest.raises(ValueError):
        validate_batch((), _response())
    too_many = tuple(Requirement(f"PSN-{i}", "VIEW") for i in range(MAX_REQUIREMENTS + 1))
    with pytest.raises(ValueError):
        validate_batch(too_many, _response())


def test_outcome_vocabulary():
    assert {ANSWERED, SESSION_INVALID, UNAVAILABLE} == {"ANSWERED", "SESSION_INVALID", "UNAVAILABLE"}
