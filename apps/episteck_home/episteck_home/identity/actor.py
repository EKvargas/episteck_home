"""Trusted actor resolution for the Home Control Plane (G1.6).

THE INVARIANT
-------------
``actor_person_id`` is NEVER an input. It is always a server-side derivation of
validated authentication context:

    validated authentication
        -> authenticated Frappe User
        -> Person.linked_user
        -> trusted Person
        -> internal actor_person_id

Neither ``actor_person_id`` nor ``User.name`` is ever a caller assertion. The caller
supplies no identity at all; ``frappe.session.user`` is set by Frappe's own
authentication (session cookie, API key, or validated OAuth bearer token) before any
business method runs.

DUAL PRINCIPAL (amendment A6)
-----------------------------
    machine_caller — the authenticated Frappe User of the calling service
    human_actor    — the Person resolved from the delegated human session

A machine credential proves only "this service may call this interface". It never
means "this service is Person X". Both principals are returned together so audit and
event context can retain both.
"""
from __future__ import annotations

from dataclasses import dataclass

import frappe


@dataclass(frozen=True)
class Principals:
    """Both principals behind a delegated request. Either may be absent."""

    human_actor: str | None
    machine_caller: str | None

    @property
    def is_delegated(self) -> bool:
        return bool(self.human_actor and self.machine_caller)

    def audit(self) -> dict:
        """Audit context retaining BOTH identities (never collapsed into one)."""
        return {
            "human_actor": self.human_actor,
            "machine_caller": self.machine_caller,
            "delegated": self.is_delegated,
        }


def _throw(message: str) -> None:
    frappe.throw(message, frappe.PermissionError)


def _mark_denial(category: str) -> None:
    """Record why a denial happened, as a static category.

    Pairs with ``frappe.local.episteck_delegation_stage`` from the auth hook: together
    they say whether the hook bound a delegated user and, if it did, whether that user
    mapped to exactly one Person. Never records an identity or a credential.
    """
    frappe.local.episteck_denial_category = category


def resolve_principals() -> Principals:
    """Resolve both principals from authenticated context only. Fail closed.

    Raises PermissionError when no human actor can be derived. A machine credential
    alone can never yield a human actor.
    """
    user = frappe.session.user
    if not user or user == "Guest":
        _throw("authentication required")

    # A delegated human session, established server-side by the auth hook. The hook
    # has already verified the delegation token and mapped its opaque session id to
    # a Frappe User; it never accepts a Person id from any caller.
    delegated_user = getattr(frappe.local, "episteck_delegated_user", None)
    machine_caller = user if delegated_user else None
    effective_user = delegated_user or user

    person = _person_for_user(effective_user)
    if not person:
        # The credential authenticated, but it is not a human actor. This is the
        # branch that makes a stolen service credential useless for person data.
        #
        # Record WHICH of the two shapes this was, so a denial is diagnosable without
        # reproducing it: either the hook never bound a delegated user (its own stage
        # code says why), or it did and the User has no unique linked Person. Static
        # categories only — no identity, no credential.
        _mark_denial(
            "actor.no_person_for_delegated_user"
            if delegated_user
            else "actor.no_delegated_user"
        )
        _throw("no human actor bound to this session")

    return Principals(human_actor=person, machine_caller=machine_caller)


def _person_for_user(user: str) -> str | None:
    """Map an authenticated Frappe User to exactly one Person, or nothing.

    Ambiguity is a denial, not a guess: if the data somehow contains more than one
    Person for a User, we fail closed rather than pick one.
    """
    people = frappe.get_all(
        "Person", filters={"linked_user": user}, fields=["name"], limit_page_length=0
    )
    if len(people) != 1:
        if len(people) > 1:
            frappe.log_error(
                f"ambiguous linked_user binding for {user}: {len(people)} Persons",
                "episteck_home.identity",
            )
        return None
    return people[0]["name"]


def resolve_actor() -> str:
    """Return the trusted actor Person id. Never accepts a caller-supplied value."""
    return resolve_principals().human_actor
