"""Synthetic KAP-1 wire vectors; no actor, credential, or live service is used."""

from __future__ import annotations

import copy
import hashlib

import pytest

from episteck_home_contracts.authorization_plan import (
    ContractError,
    DomainRoute,
    parse_plan_request,
    parse_plan_response,
    parse_revalidation_request,
    parse_revalidation_response,
)


VERSION_DIGEST = "a" * 64


def _knowledge_operation() -> dict:
    return {
        "operation_id": "op-k",
        "kind": "KNOWLEDGE_READ",
        "use_class": "ORDINARY_READ",
        "requirements": [
            {"resource_type": "PERSON", "resource_id": "PSN-1", "domain": "KNOWLEDGE", "action": "VIEW"},
            {"resource_type": "PERSON", "resource_id": "PSN-1", "domain": "NUTRITION", "action": "VIEW"},
        ],
        "target": {
            "owner": "KNOWLEDGE",
            "exact_versions": [
                {
                    "version_id": "version-1",
                    "classification_revision": "c1",
                    "control_revision": "l1",
                    "requirement_digest": VERSION_DIGEST,
                }
            ],
            "requested_interval": None,
        },
        "domain_request": None,
    }


def _plan() -> dict:
    return {"version": 1, "request_id": "request-1", "operations": [_knowledge_operation()]}


def _trusted_manifest() -> dict:
    op = _knowledge_operation()
    return {"op-k": {"requirements": op["requirements"], "target": op["target"]}}


def _response(digest: str) -> dict:
    return {
        "message": {
            "version": 1,
            "request_id": "request-1",
            "plan_id": "plan-1",
            "plan_context": "context-1",
            "expires_at": 1790000060,
            "authorization_revision": "revision-1",
            "window_id": "window-1",
            "decisions": [
                {
                    "operation_id": "op-k",
                    "requirement_digest": digest,
                    "outcome": "ALLOW",
                    "decision_id": "decision-1",
                    "execution_basis": None,
                }
            ],
        }
    }


def _revalidation() -> dict:
    return {
        "version": 1,
        "request_id": "request-1",
        "plan_id": "plan-1",
        "contributions": [
            {
                "operation_id": "op-k",
                "selected_versions": [
                    {"version_id": "version-1", "classification_revision": "c1", "control_revision": "l1"}
                ],
                "domain_results": [],
            }
        ],
    }


def _domain_operation() -> dict:
    body = {"subject_person_ids": ["PSN-1"], "resource_ids": ["record-1"], "query": {"limit": 10}}
    import rfc8785

    return {
        "operation_id": "op-n",
        "kind": "DOMAIN_READ",
        "use_class": "ORDINARY_READ",
        "requirements": [{"resource_type": "PERSON", "resource_id": "PSN-1", "domain": "NUTRITION", "action": "VIEW"}],
        "target": {"owner": "DOMAIN", "resource_ids": ["record-1"]},
        "domain_request": {
            "audience": "spiffe://episteck.internal/service/svc-nutrition",
            "method": "POST",
            "target": "/v1/r13/knowledge-read",
            "body": body,
            "request_sha256": hashlib.sha256(rfc8785.dumps(body)).hexdigest(),
        },
    }


def _route() -> DomainRoute:
    def validate_body(body: dict) -> None:
        if set(body) != {"subject_person_ids", "resource_ids", "query"} or body["query"] != {"limit": 10}:
            raise ContractError("adapter body mismatch")

    def validate_result(result: dict, basis: dict) -> tuple[str, str]:
        if set(result) != {"resource_id", "revision", "execution_id"} or result["revision"] != "r1":
            raise ContractError("adapter result mismatch")
        if result["execution_id"] != "execution-1":
            raise ContractError("execution mismatch")
        return result["resource_id"], result["execution_id"]

    return DomainRoute(
        audience="spiffe://episteck.internal/service/svc-nutrition",
        method="POST",
        target="/v1/r13/knowledge-read",
        domain="NUTRITION",
        action="VIEW",
        use_class="ORDINARY_READ",
        validate_body=validate_body,
        validate_result=validate_result,
    )


def test_knowledge_plan_vector_has_stable_jcs_digest():
    plan = parse_plan_request(_plan(), trusted_manifest=_trusted_manifest())
    assert len(plan.operations) == 1
    assert plan.operation_digests == (
        hashlib.sha256(
            b'{"domain_request":null,"kind":"KNOWLEDGE_READ","operation_id":"op-k","requirements":'
            b'[{"action":"VIEW","domain":"KNOWLEDGE","resource_id":"PSN-1","resource_type":"PERSON"},'
            b'{"action":"VIEW","domain":"NUTRITION","resource_id":"PSN-1","resource_type":"PERSON"}],'
            b'"target":{"exact_versions":[{"classification_revision":"c1","control_revision":"l1",'
            b'"requirement_digest":"' + VERSION_DIGEST.encode() + b'","version_id":"version-1"}],'
            b'"owner":"KNOWLEDGE","requested_interval":null},"use_class":"ORDINARY_READ"}'
        ).hexdigest(),
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda plan: plan.update(actor_person_id="PSN-1"),
        lambda plan: plan.update(partition_id="partition-1"),
        lambda plan: plan["operations"][0]["requirements"].reverse(),
        lambda plan: plan["operations"][0]["requirements"].append(plan["operations"][0]["requirements"][0]),
        lambda plan: plan["operations"][0]["requirements"].pop(),
        lambda plan: plan["operations"][0]["target"]["exact_versions"].append(
            plan["operations"][0]["target"]["exact_versions"][0]
        ),
    ],
)
def test_plan_rejects_identity_order_duplicates_and_incomplete_requirements(change):
    payload = _plan()
    change(payload)
    with pytest.raises(ContractError):
        parse_plan_request(payload, trusted_manifest=_trusted_manifest())


def test_plan_rejects_duplicate_json_keys_and_oversize():
    with pytest.raises(ContractError):
        parse_plan_request('{"version":1,"version":1,"request_id":"r","operations":[]}', trusted_manifest={})
    oversized = _plan()
    oversized["request_id"] = "r" * 65536
    with pytest.raises(ContractError):
        parse_plan_request(oversized, trusted_manifest=_trusted_manifest())


def test_response_rejects_altered_digest_and_invalid_basis_rule():
    plan = parse_plan_request(_plan(), trusted_manifest=_trusted_manifest())
    parsed = parse_plan_response(_response(plan.operation_digests[0]), plan)
    assert parsed.decisions[0].outcome == "ALLOW"
    altered = _response("f" * 64)
    with pytest.raises(ContractError):
        parse_plan_response(altered, plan)
    wrong_basis = _response(plan.operation_digests[0])
    wrong_basis["message"]["decisions"][0]["execution_basis"] = {"claims_jcs_b64u": "x", "signature_hex": "f" * 128}
    with pytest.raises(ContractError):
        parse_plan_response(wrong_basis, plan)


def test_response_rejects_missing_or_reordered_decisions():
    payload = _plan()
    second = copy.deepcopy(_knowledge_operation())
    second["operation_id"] = "op-z"
    payload["operations"].append(second)
    manifest = _trusted_manifest()
    manifest["op-z"] = {"requirements": second["requirements"], "target": second["target"]}
    plan = parse_plan_request(payload, trusted_manifest=manifest)
    response = _response(plan.operation_digests[0])
    with pytest.raises(ContractError):
        parse_plan_response(response, plan)
    response["message"]["decisions"].append(
        {"operation_id": "op-z", "requirement_digest": plan.operation_digests[1], "outcome": "DENY", "decision_id": "d2", "execution_basis": None}
    )
    response["message"]["decisions"].reverse()
    with pytest.raises(ContractError):
        parse_plan_response(response, plan)


def test_revalidation_rejects_out_of_plan_and_changed_version():
    plan = parse_plan_request(_plan(), trusted_manifest=_trusted_manifest())
    response = parse_plan_response(_response(plan.operation_digests[0]), plan)
    parsed = parse_revalidation_request(_revalidation(), plan, response)
    assert parsed.contributions[0].operation_id == "op-k"
    unknown = _revalidation()
    unknown["contributions"][0]["operation_id"] = "op-unknown"
    with pytest.raises(ContractError):
        parse_revalidation_request(unknown, plan, response)
    changed = _revalidation()
    changed["contributions"][0]["selected_versions"][0]["control_revision"] = "l2"
    with pytest.raises(ContractError):
        parse_revalidation_request(changed, plan, response)


def test_revalidation_response_requires_fresh_complete_allow():
    plan = parse_plan_request(_plan(), trusted_manifest=_trusted_manifest())
    response = parse_plan_response(_response(plan.operation_digests[0]), plan)
    request = parse_revalidation_request(_revalidation(), plan, response)
    result = {
        "message": {
            "version": 1,
            "request_id": "request-1",
            "plan_id": "plan-1",
            "evaluated_at": 1790000030,
            "authorization_revision": "revision-2",
            "disclosure_fence": "fence-2",
            "decisions": [{"operation_id": "op-k", "outcome": "ALLOW"}],
            "disclosure": "ALLOW",
        }
    }
    assert parse_revalidation_response(result, request).disclosure == "ALLOW"
    result["message"]["decisions"][0]["outcome"] = "DENY"
    with pytest.raises(ContractError):
        parse_revalidation_response(result, request)


def test_domain_read_requires_registered_route_and_exact_body_hash():
    op = _domain_operation()
    payload = {"version": 1, "request_id": "request-1", "operations": [op]}
    manifest = {"op-n": {"requirements": op["requirements"], "target": op["target"]}}
    with pytest.raises(ContractError):
        parse_plan_request(payload, trusted_manifest=manifest)
    routes = {_route().audience: _route()}
    assert parse_plan_request(payload, trusted_manifest=manifest, domain_routes=routes).operations[0].kind == "DOMAIN_READ"
    op["domain_request"]["body"]["query"]["limit"] = 11
    with pytest.raises(ContractError):
        parse_plan_request(payload, trusted_manifest=manifest, domain_routes=routes)


def test_domain_read_rejects_missing_subject_requirement():
    op = _domain_operation()
    op["domain_request"]["body"]["subject_person_ids"].append("PSN-2")
    import rfc8785

    op["domain_request"]["request_sha256"] = hashlib.sha256(rfc8785.dumps(op["domain_request"]["body"])).hexdigest()
    payload = {"version": 1, "request_id": "request-1", "operations": [op]}
    manifest = {"op-n": {"requirements": op["requirements"], "target": op["target"]}}
    with pytest.raises(ContractError):
        parse_plan_request(payload, trusted_manifest=manifest, domain_routes={_route().audience: _route()})


def test_domain_body_rejects_identity_authority_fields():
    op = _domain_operation()
    op["domain_request"]["body"]["actor_person_id"] = "PSN-1"
    import rfc8785

    op["domain_request"]["request_sha256"] = hashlib.sha256(rfc8785.dumps(op["domain_request"]["body"])).hexdigest()
    payload = {"version": 1, "request_id": "request-1", "operations": [op]}
    manifest = {"op-n": {"requirements": op["requirements"], "target": op["target"]}}
    permissive_route = DomainRoute(
        **{**_route().__dict__, "validate_body": lambda body: None}
    )
    with pytest.raises(ContractError):
        parse_plan_request(payload, trusted_manifest=manifest, domain_routes={permissive_route.audience: permissive_route})


def test_domain_contribution_requires_adapter_and_in_plan_result():
    op = _domain_operation()
    payload = {"version": 1, "request_id": "request-1", "operations": [op]}
    manifest = {"op-n": {"requirements": op["requirements"], "target": op["target"]}}
    route = _route()
    routes = {route.audience: route}
    plan = parse_plan_request(payload, trusted_manifest=manifest, domain_routes=routes)
    response = _response(plan.operation_digests[0])
    response["message"]["decisions"][0]["operation_id"] = "op-n"
    response["message"]["decisions"][0]["execution_basis"] = {
        "claims_jcs_b64u": "eA",
        "signature_hex": "f" * 128,
    }
    approved = parse_plan_response(response, plan)
    rt2 = {
        "version": 1,
        "request_id": "request-1",
        "plan_id": "plan-1",
        "contributions": [{
            "operation_id": "op-n",
            "selected_versions": [],
            "domain_results": [{"resource_id": "record-1", "revision": "r1", "execution_id": "execution-1"}],
        }],
    }
    with pytest.raises(ContractError):
        parse_revalidation_request(rt2, plan, approved)
    assert parse_revalidation_request(rt2, plan, approved, domain_routes=routes).contributions[0].operation_id == "op-n"
    rt2["contributions"][0]["domain_results"][0]["resource_id"] = "hidden-record"
    with pytest.raises(ContractError):
        parse_revalidation_request(rt2, plan, approved, domain_routes=routes)


def test_non_null_interval_requires_trusted_knowledge_validator():
    payload = _plan()
    payload["operations"][0]["target"]["requested_interval"] = {"from": 100, "until": 200}
    manifest = _trusted_manifest()
    manifest["op-k"]["target"] = copy.deepcopy(payload["operations"][0]["target"])
    with pytest.raises(ContractError):
        parse_plan_request(payload, trusted_manifest=manifest)

    def validate_interval(interval: dict) -> None:
        if set(interval) != {"from", "until"} or interval["from"] > interval["until"]:
            raise ContractError("invalid interval")

    assert parse_plan_request(payload, trusted_manifest=manifest, validate_interval=validate_interval).operations[0].kind == "KNOWLEDGE_READ"


def test_determinate_denial_is_valid_but_cannot_contribute():
    plan = parse_plan_request(_plan(), trusted_manifest=_trusted_manifest())
    raw = _response(plan.operation_digests[0])
    raw["message"]["decisions"][0]["outcome"] = "DENY"
    denied = parse_plan_response(raw, plan)
    assert denied.decisions[0].outcome == "DENY"
    with pytest.raises(ContractError):
        parse_revalidation_request(_revalidation(), plan, denied)
