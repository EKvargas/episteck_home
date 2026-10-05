"""KAP-1 v1 wire validation. This module makes no authorization decision.

The caller must supply the protected Knowledge manifest. Validation never
turns a caller-supplied requirement list into proof that the list is complete.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import rfc8785

from .context import VALID_ACTIONS, VALID_DOMAINS


MAX_BODY = 64 * 1024
MAX_OPERATIONS = 32
MAX_REQUIREMENTS = 256
MAX_VERSIONS = 128
_HEX256 = re.compile(r"[0-9a-f]{64}\Z")
_HEX512 = re.compile(r"[0-9a-f]{128}\Z")
_B64U = re.compile(r"[A-Za-z0-9_-]+\Z")
_FORBIDDEN_IDENTITY_FIELDS = frozenset(
    {
        "actor_person_id",
        "partition_id",
        "user",
        "user_id",
        "sid",
        "session_id",
        "delegation",
        "caller_service",
        "caller_spki_sha256",
    }
)


class ContractError(ValueError):
    """A wire value is malformed, unsupported, or unbound to trusted state."""


@dataclass(frozen=True)
class DomainRoute:
    """Trusted adapter registration, including strict domain body/result schemas.

    validate_result must compare the result execution ID with the issued basis.
    The owning adapter defines its revision or freshness-marker wire fields.
    """

    audience: str
    method: str
    target: str
    domain: str
    action: str
    use_class: str
    validate_body: Callable[[dict[str, Any]], None]
    validate_result: Callable[[dict[str, Any], dict[str, str]], tuple[str, str]]


@dataclass(frozen=True)
class Requirement:
    resource_type: str
    resource_id: str
    domain: str
    action: str


@dataclass(frozen=True)
class ExactVersion:
    version_id: str
    classification_revision: str
    control_revision: str
    requirement_digest: str


@dataclass(frozen=True)
class PlanOperation:
    operation_id: str
    kind: str
    use_class: str
    requirements: tuple[Requirement, ...]
    owner: str
    exact_versions: tuple[ExactVersion, ...]
    resource_ids: tuple[str, ...]
    domain_audience: str | None
    digest: str


@dataclass(frozen=True)
class PlanRequest:
    request_id: str
    operations: tuple[PlanOperation, ...]

    @property
    def operation_digests(self) -> tuple[str, ...]:
        return tuple(operation.digest for operation in self.operations)


@dataclass(frozen=True)
class PlanDecision:
    operation_id: str
    outcome: str
    decision_id: str
    execution_basis: Mapping[str, str] | None


@dataclass(frozen=True)
class PlanResponse:
    request_id: str
    plan_id: str
    plan_context: str
    expires_at: int
    authorization_revision: str
    window_id: str
    decisions: tuple[PlanDecision, ...]


@dataclass(frozen=True)
class Contribution:
    operation_id: str
    selected_versions: tuple[tuple[str, str, str], ...]
    domain_results: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RevalidationRequest:
    request_id: str
    plan_id: str
    contributions: tuple[Contribution, ...]


@dataclass(frozen=True)
class RevalidationResponse:
    request_id: str
    plan_id: str
    evaluated_at: int
    authorization_revision: str
    disclosure_fence: str
    decisions: tuple[tuple[str, str], ...]
    disclosure: str


def _duplicate_reject(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON key")
        result[key] = value
    return result


def _constant_reject(value: str) -> None:
    raise ContractError("non-JSON numeric value")


def _wire(value: bytes | str | Mapping[str, Any], *, limit: int = MAX_BODY) -> dict[str, Any]:
    try:
        if isinstance(value, (bytes, str)):
            value = json.loads(value, object_pairs_hook=_duplicate_reject, parse_constant=_constant_reject)
        canonical = rfc8785.dumps(value)
        if len(canonical) > limit:
            raise ContractError("wire body exceeds bound")
    except (UnicodeError, json.JSONDecodeError, TypeError, rfc8785.CanonicalizationError) as exc:
        raise ContractError("invalid JSON body") from exc
    if type(value) is not dict:
        raise ContractError("wire body must be an object")
    return value


def _object(value: Any, fields: set[str], name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ContractError(f"invalid {name} fields")
    return value


def _array(value: Any, lower: int, upper: int, name: str) -> list[Any]:
    if type(value) is not list or not lower <= len(value) <= upper:
        raise ContractError(f"invalid {name} count")
    return value


def _id(value: Any, name: str) -> str:
    if type(value) is not str or not value or any(ord(ch) < 33 or ord(ch) > 126 for ch in value):
        raise ContractError(f"invalid {name}")
    return value


def _enum(value: Any, allowed: set[str] | frozenset[str], name: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ContractError(f"invalid {name}")
    return value


def _integer(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ContractError(f"invalid {name}")
    return value


def _digest(value: Any, name: str) -> str:
    if type(value) is not str or not _HEX256.fullmatch(value):
        raise ContractError(f"invalid {name}")
    return value


def _reject_identity_fields(value: Any) -> None:
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is str and key.casefold() in _FORBIDDEN_IDENTITY_FIELDS:
                raise ContractError("caller-supplied identity authority field")
            _reject_identity_fields(child)
    elif type(value) is list:
        for child in value:
            _reject_identity_fields(child)


def _requirements(value: Any) -> tuple[Requirement, ...]:
    raw = _array(value, 1, 64, "requirements")
    result = []
    for item in raw:
        item = _object(item, {"resource_type", "resource_id", "domain", "action"}, "requirement")
        result.append(
            Requirement(
                _enum(item["resource_type"], {"PERSON", "CIRCLE"}, "resource type"),
                _id(item["resource_id"], "resource id"),
                _enum(item["domain"], VALID_DOMAINS, "domain"),
                _enum(item["action"], VALID_ACTIONS, "action"),
            )
        )
    keys = [(v.resource_type, v.resource_id, v.domain, v.action) for v in result]
    if keys != sorted(set(keys)):
        raise ContractError("requirements are not normalized and unique")
    if any(v.action != "VIEW" for v in result):
        raise ContractError("read operation requires VIEW tuples")
    return tuple(result)


def _versions(value: Any) -> tuple[ExactVersion, ...]:
    raw = _array(value, 1, MAX_VERSIONS, "exact versions")
    result = []
    for item in raw:
        item = _object(item, {"version_id", "classification_revision", "control_revision", "requirement_digest"}, "exact version")
        result.append(
            ExactVersion(
                _id(item["version_id"], "version id"),
                _id(item["classification_revision"], "classification revision"),
                _id(item["control_revision"], "control revision"),
                _digest(item["requirement_digest"], "version requirement digest"),
            )
        )
    ids = [v.version_id for v in result]
    if ids != sorted(set(ids)):
        raise ContractError("exact versions are not normalized and unique")
    return tuple(result)


def _operation(
    value: Any,
    trusted: Mapping[str, Any] | None,
    domain_routes: Mapping[str, DomainRoute],
    validate_interval: Callable[[Any], None] | None,
) -> PlanOperation:
    item = _object(value, {"operation_id", "kind", "use_class", "requirements", "target", "domain_request"}, "operation")
    operation_id = _id(item["operation_id"], "operation id")
    kind = _enum(item["kind"], {"KNOWLEDGE_READ", "DOMAIN_READ"}, "operation kind")
    use_class = _enum(item["use_class"], {"ORDINARY_READ"}, "use class")
    requirements = _requirements(item["requirements"])
    if trusted is None or item["requirements"] != trusted.get("requirements") or item["target"] != trusted.get("target"):
        raise ContractError("operation is not bound to trusted protected metadata")
    if kind == "KNOWLEDGE_READ":
        target = _object(item["target"], {"owner", "exact_versions", "requested_interval"}, "Knowledge target")
        if target["owner"] != "KNOWLEDGE" or item["domain_request"] is not None:
            raise ContractError("unsupported Knowledge target")
        if target["requested_interval"] is not None:
            if validate_interval is None:
                raise ContractError("Knowledge interval contract is not registered")
            try:
                validate_interval(copy.deepcopy(target["requested_interval"]))
            except Exception:
                raise ContractError("invalid Knowledge interval") from None
        versions = _versions(target["exact_versions"])
        if not any(r.domain == "KNOWLEDGE" and r.action == "VIEW" for r in requirements):
            raise ContractError("Knowledge read lacks Knowledge VIEW")
        resource_ids: tuple[str, ...] = ()
        owner = "KNOWLEDGE"
        domain_audience = None
    else:
        target = _object(item["target"], {"owner", "resource_ids"}, "domain target")
        if target["owner"] != "DOMAIN":
            raise ContractError("unsupported domain target")
        ids = _array(target["resource_ids"], 1, MAX_BODY, "domain resources")
        resource_ids = tuple(_id(v, "domain resource id") for v in ids)
        if list(resource_ids) != sorted(set(resource_ids)):
            raise ContractError("domain resources are not normalized and unique")
        if type(item["domain_request"]) is not dict:
            raise ContractError("domain request required")
        domain_request = _object(item["domain_request"], {"audience", "method", "target", "body", "request_sha256"}, "domain request")
        domain_audience = _id(domain_request["audience"], "domain audience")
        route = domain_routes.get(domain_audience)
        if route is None or domain_audience != route.audience or (domain_request["method"], domain_request["target"], use_class) != (route.method, route.target, route.use_class):
            raise ContractError("unregistered domain route")
        if route.method != "POST" or not route.target.startswith("/") or "?" in route.target:
            raise ContractError("unsupported domain route")
        if type(domain_request["body"]) is not dict:
            raise ContractError("domain body must be an object")
        body = domain_request["body"]
        subjects = _array(body.get("subject_person_ids"), 1, 64, "domain subjects")
        subjects = [_id(subject, "domain subject") for subject in subjects]
        resources = _array(body.get("resource_ids"), 1, MAX_BODY, "domain body resources")
        resources = [_id(resource, "domain body resource") for resource in resources]
        if subjects != sorted(set(subjects)) or resources != list(resource_ids):
            raise ContractError("domain body targets are not normalized or bound")
        expected_requirements = {(subject, route.domain, route.action) for subject in subjects}
        actual_requirements = {(r.resource_id, r.domain, r.action) for r in requirements if r.resource_type == "PERSON"}
        if len(actual_requirements) != len(requirements) or actual_requirements != expected_requirements:
            raise ContractError("domain basis cannot cover full requirement set")
        if _digest(domain_request["request_sha256"], "domain request hash") != hashlib.sha256(rfc8785.dumps(body)).hexdigest():
            raise ContractError("domain request hash mismatch")
        try:
            route.validate_body(copy.deepcopy(body))
        except Exception:
            raise ContractError("invalid domain request body") from None
        versions = ()
        owner = "DOMAIN"
    try:
        digest = hashlib.sha256(rfc8785.dumps(item)).hexdigest()
    except rfc8785.CanonicalizationError as exc:
        raise ContractError("operation is not canonicalizable") from exc
    return PlanOperation(operation_id, kind, use_class, requirements, owner, versions, resource_ids, domain_audience, digest)


def parse_plan_request(
    value: bytes | str | Mapping[str, Any], *, trusted_manifest: Mapping[str, Mapping[str, Any]],
    domain_routes: Mapping[str, DomainRoute] | None = None,
    validate_interval: Callable[[Any], None] | None = None,
) -> PlanRequest:
    """Validate RT#1 structure and exact binding to trusted protected metadata."""
    body = _object(_wire(value), {"version", "request_id", "operations"}, "plan")
    _reject_identity_fields(body)
    if type(body["version"]) is not int or body["version"] != 1:
        raise ContractError("unsupported plan version")
    request_id = _id(body["request_id"], "request id")
    raw = _array(body["operations"], 1, MAX_OPERATIONS, "operations")
    operations = tuple(
        _operation(item, trusted_manifest.get(item.get("operation_id")) if type(item) is dict else None, domain_routes or {}, validate_interval)
        for item in raw
    )
    ids = [op.operation_id for op in operations]
    if ids != sorted(set(ids)) or set(ids) != set(trusted_manifest):
        raise ContractError("operations are not normalized and complete")
    if sum(len(op.requirements) for op in operations) > MAX_REQUIREMENTS:
        raise ContractError("plan requirement bound exceeded")
    return PlanRequest(request_id, operations)


def parse_plan_response(value: bytes | str | Mapping[str, Any], request: PlanRequest) -> PlanResponse:
    """Reject missing, altered, extra or reordered RT#1 decisions."""
    wrapper = _object(_wire(value), {"message"}, "Frappe response")
    body = _object(wrapper["message"], {"version", "request_id", "plan_id", "plan_context", "expires_at", "authorization_revision", "window_id", "decisions"}, "plan response")
    if body["version"] != 1 or type(body["version"]) is not int or body["request_id"] != request.request_id:
        raise ContractError("plan response binding mismatch")
    raw = _array(body["decisions"], len(request.operations), len(request.operations), "decisions")
    decisions = []
    for op, decision in zip(request.operations, raw, strict=True):
        decision = _object(decision, {"operation_id", "requirement_digest", "outcome", "decision_id", "execution_basis"}, "plan decision")
        outcome = _enum(decision["outcome"], {"ALLOW", "DENY"}, "outcome")
        if decision["operation_id"] != op.operation_id or decision["requirement_digest"] != op.digest:
            raise ContractError("plan decision order or digest mismatch")
        basis = decision["execution_basis"]
        if outcome == "ALLOW" and op.kind == "DOMAIN_READ":
            basis = _object(basis, {"claims_jcs_b64u", "signature_hex"}, "execution basis")
            if not _B64U.fullmatch(_id(basis["claims_jcs_b64u"], "basis claims")) or not _HEX512.fullmatch(_id(basis["signature_hex"], "basis signature")):
                raise ContractError("malformed execution basis")
        elif basis is not None:
            raise ContractError("unexpected execution basis")
        decisions.append(PlanDecision(op.operation_id, outcome, _id(decision["decision_id"], "decision id"), basis))
    return PlanResponse(
        request.request_id,
        _id(body["plan_id"], "plan id"),
        _id(body["plan_context"], "plan context"),
        _integer(body["expires_at"], "expiry"),
        _id(body["authorization_revision"], "authorization revision"),
        _id(body["window_id"], "window id"),
        tuple(decisions),
    )


def parse_revalidation_request(
    value: bytes | str | Mapping[str, Any], plan: PlanRequest, response: PlanResponse,
    *, domain_routes: Mapping[str, DomainRoute] | None = None,
) -> RevalidationRequest:
    """Bind RT#2 contributors to RT#1 allows and exact Knowledge versions."""
    body = _object(_wire(value), {"version", "request_id", "plan_id", "contributions"}, "revalidation request")
    if type(body["version"]) is not int or body["version"] != 1 or body["request_id"] != plan.request_id or body["plan_id"] != response.plan_id:
        raise ContractError("revalidation request binding mismatch")
    raw = _array(body["contributions"], 1, len(plan.operations), "contributions")
    by_id = {op.operation_id: (index, op, response.decisions[index]) for index, op in enumerate(plan.operations)}
    contributions = []
    previous_index = -1
    for item in raw:
        item = _object(item, {"operation_id", "selected_versions", "domain_results"}, "contribution")
        operation_id = _id(item["operation_id"], "contributing operation id")
        if operation_id not in by_id:
            raise ContractError("out-of-plan contribution")
        index, operation, decision = by_id[operation_id]
        if index <= previous_index or decision.outcome != "ALLOW":
            raise ContractError("duplicate, reordered or denied contribution")
        previous_index = index
        if operation.kind == "KNOWLEDGE_READ":
            if item["domain_results"] != []:
                raise ContractError("Knowledge contribution cannot contain domain results")
            raw_versions = _array(item["selected_versions"], 1, len(operation.exact_versions), "selected versions")
            versions = []
            for version in raw_versions:
                version = _object(version, {"version_id", "classification_revision", "control_revision"}, "selected version")
                versions.append(tuple(_id(version[key], key) for key in ("version_id", "classification_revision", "control_revision")))
            expected = {(v.version_id, v.classification_revision, v.control_revision) for v in operation.exact_versions}
            if len(set(versions)) != len(versions) or versions != sorted(versions) or not set(versions) <= expected:
                raise ContractError("selected versions changed or repeated")
            contributions.append(Contribution(operation_id, tuple(versions)))
        else:
            if item["selected_versions"] != []:
                raise ContractError("domain contribution cannot contain Knowledge versions")
            route = (domain_routes or {}).get(operation.domain_audience or "")
            basis = decision.execution_basis
            if route is None or route.audience != operation.domain_audience or basis is None:
                raise ContractError("domain result wire contract is not registered")
            raw_results = _array(item["domain_results"], 1, len(operation.resource_ids), "domain results")
            results = []
            for result in raw_results:
                if type(result) is not dict:
                    raise ContractError("domain result must be an object")
                try:
                    resource_id, execution_id = route.validate_result(result, dict(basis))
                except Exception:
                    raise ContractError("invalid domain result binding") from None
                results.append((_id(resource_id, "domain result resource"), _id(execution_id, "domain execution id")))
            if (
                len({r[0] for r in results}) != len(results)
                or len({r[1] for r in results}) != 1
                or [r[0] for r in results] != sorted(r[0] for r in results)
                or not {r[0] for r in results} <= set(operation.resource_ids)
            ):
                raise ContractError("domain result is duplicated, unordered or out of plan")
            contributions.append(Contribution(operation_id, (), tuple(results)))
    return RevalidationRequest(plan.request_id, response.plan_id, tuple(contributions))


def parse_revalidation_response(
    value: bytes | str | Mapping[str, Any], request: RevalidationRequest
) -> RevalidationResponse:
    """Validate a complete fresh RT#2 result; DENY is a determinate outcome."""
    wrapper = _object(_wire(value), {"message"}, "Frappe response")
    body = _object(wrapper["message"], {"version", "request_id", "plan_id", "evaluated_at", "authorization_revision", "disclosure_fence", "decisions", "disclosure"}, "revalidation response")
    if type(body["version"]) is not int or body["version"] != 1 or body["request_id"] != request.request_id or body["plan_id"] != request.plan_id:
        raise ContractError("revalidation response binding mismatch")
    raw = _array(body["decisions"], len(request.contributions), len(request.contributions), "fresh decisions")
    decisions = []
    for contribution, decision in zip(request.contributions, raw, strict=True):
        decision = _object(decision, {"operation_id", "outcome"}, "fresh decision")
        if decision["operation_id"] != contribution.operation_id:
            raise ContractError("fresh decision order mismatch")
        decisions.append((contribution.operation_id, _enum(decision["outcome"], {"ALLOW", "DENY"}, "fresh outcome")))
    disclosure = _enum(body["disclosure"], {"ALLOW", "DENY"}, "disclosure")
    if (disclosure == "ALLOW") != all(outcome == "ALLOW" for _, outcome in decisions):
        raise ContractError("disclosure contradicts fresh decisions")
    return RevalidationResponse(
        request.request_id,
        request.plan_id,
        _integer(body["evaluated_at"], "evaluation time"),
        _id(body["authorization_revision"], "authorization revision"),
        _id(body["disclosure_fence"], "disclosure fence"),
        tuple(decisions),
        disclosure,
    )
