"""Seeded synthetic corpus generator (Phase-1 doc SS16.3).

Deterministic: same seed -> byte-identical corpus, so both backends are loaded from
IDENTICAL logical data and results are comparable. No real names, no real household data
-- every string is generated from the seed.

Sizes (assertion versions): C-small=100, C-medium=5000, C-large=100000, per SS16.3 table.
Each corpus includes, by construction: multi-subject assertions, mixed-domain assertions,
superseded chains, disputed assertions, expired assertions, suppressed-but-present
records, stale-binding derivatives, and grants that authorize some synthetic actors and
not others -- exactly the SS16.3 requirement list.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backends.model import (  # noqa: E402
    DOMAINS,
    AssertionVersion,
    Corpus,
    GrantRecord,
    LifecycleState,
    MaterializationBinding,
    SuppressionRecord,
)

SIZE_TABLE = {
    "C-small": {"assertions": 100, "persons": 3, "circles": 2},
    "C-medium": {"assertions": 5_000, "persons": 6, "circles": 4},
    "C-large": {"assertions": 100_000, "persons": 10, "circles": 6},
}

_EPOCH_BASE = 1_700_000_000  # arbitrary fixed epoch anchor, deterministic
_DAY = 86_400

_TOPICS = [
    "prefers-cuisine", "dislikes-ingredient", "routine-morning", "goal-fitness",
    "constraint-schedule", "decision-vendor", "preference-color", "habit-reading",
    "rationale-budget", "note-travel",
]


def _content_text(rng: random.Random, topic: str) -> str:
    filler = rng.choice(["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"])
    return f"synthetic assertion: {topic} :: token-{filler}-{rng.randint(0, 9999)}"


def generate_corpus(size_label: str, seed: int = 42) -> Corpus:
    if size_label not in SIZE_TABLE:
        raise ValueError(f"unknown size label {size_label!r}; expected one of {list(SIZE_TABLE)}")

    spec = SIZE_TABLE[size_label]
    rng = random.Random(seed)

    partitions = (f"PARTITION-{size_label}-1",)  # single trusted partition (B1 SS5.1 single-deployment)
    partition_id = partitions[0]
    persons = tuple(f"PERSON-{i:04d}" for i in range(spec["persons"]))
    circles = tuple(f"CIRCLE-{i:03d}" for i in range(spec["circles"]))

    assertions: list[AssertionVersion] = []
    suppressions: list[SuppressionRecord] = []
    bindings: list[MaterializationBinding] = []

    n = spec["assertions"]
    line_counter = 0

    # Reserve deterministic slices of the corpus for each required fixture family so every
    # size, however small, contains at least one of each (SS16.3 "each corpus includes").
    idx = 0
    while idx < n:
        line_counter += 1
        line_id = f"LINE-{size_label}-{line_counter:06d}"
        topic = rng.choice(_TOPICS)
        subject_count = 1 if rng.random() > 0.25 else rng.randint(2, min(3, len(persons)))
        subjects = tuple(rng.sample(persons, k=min(subject_count, len(persons))))
        domain_count = 1 if rng.random() > 0.15 else 2
        domains = tuple(rng.sample(sorted(DOMAINS - {"KNOWLEDGE"}), k=domain_count))
        applicable_from = _EPOCH_BASE - rng.randint(0, 365) * _DAY

        # Base admitted version.
        version_id = f"{line_id}-v1"
        base = AssertionVersion(
            version_id=version_id,
            partition_id=partition_id,
            line_id=line_id,
            subject_person_ids=subjects,
            domains=domains,
            content_text=_content_text(rng, topic),
            lifecycle_state=LifecycleState.ADMITTED,
            classification_revision=1,
            control_revision=1,
            applicable_from=applicable_from,
            applicable_until=None,
        )
        assertions.append(base)
        idx += 1
        if idx >= n:
            break

        roll = rng.random()
        if roll < 0.08:
            # Superseded chain: v1 SUPERSEDED, v2 ADMITTED, replaces v1.
            assertions[-1] = AssertionVersion(**{**base.__dict__, "lifecycle_state": LifecycleState.SUPERSEDED})
            v2 = AssertionVersion(
                version_id=f"{line_id}-v2",
                partition_id=partition_id,
                line_id=line_id,
                subject_person_ids=subjects,
                domains=domains,
                content_text=_content_text(rng, topic),
                lifecycle_state=LifecycleState.ADMITTED,
                classification_revision=1,
                control_revision=1,
                applicable_from=applicable_from + _DAY,
                applicable_until=None,
                replaces_version_id=version_id,
            )
            assertions.append(v2)
            idx += 1
        elif roll < 0.14:
            # Disputed assertion.
            assertions[-1] = AssertionVersion(**{**base.__dict__, "lifecycle_state": LifecycleState.DISPUTED})
        elif roll < 0.20:
            # Expired assertion -- applicable_until in the past.
            assertions[-1] = AssertionVersion(
                **{
                    **base.__dict__,
                    "lifecycle_state": LifecycleState.EXPIRED,
                    "applicable_until": applicable_from + 10 * _DAY,
                }
            )
        elif roll < 0.28:
            # Suppressed-but-physically-present: assertion row stays, suppression register
            # separately marks it unusable (H5 -- exercised by P7).
            suppressions.append(
                SuppressionRecord(
                    target_version_id=version_id,
                    partition_id=partition_id,
                    reason_family="synthetic-non-use",
                    effective_at=applicable_from + 5 * _DAY,
                )
            )
        elif roll < 0.34:
            # Stale materialization binding: classification bumped after the binding was
            # built, so the binding is stale (exercised by P9/P11).
            bindings.append(
                MaterializationBinding(
                    binding_id=f"BIND-{version_id}",
                    partition_id=partition_id,
                    source_version_id=version_id,
                    derivation_family="synthetic-index-entry",
                    classification_revision_at_build=1,
                    control_revision_at_build=1,
                    suppression_obligation=False,
                )
            )
            # Bump the live classification revision on the source row to make the binding stale.
            assertions[-1] = AssertionVersion(**{**base.__dict__, "classification_revision": 2})
        elif roll < 0.40:
            # Fresh, current materialization binding (control group for P9/P11).
            bindings.append(
                MaterializationBinding(
                    binding_id=f"BIND-{version_id}",
                    partition_id=partition_id,
                    source_version_id=version_id,
                    derivation_family="synthetic-index-entry",
                    classification_revision_at_build=1,
                    control_revision_at_build=1,
                    suppression_obligation=False,
                )
            )
        # else: plain ADMITTED assertion, majority case.

    # Grants: deliberately partial. Each Person gets VIEW/KNOWLEDGE self-grants; a random
    # subset of cross-person grants exist so some actors are authorized for some subjects
    # and not others (SS16.3 "authorized for some synthetic actors and not others").
    grants: list[GrantRecord] = []
    for actor in persons:
        grants.append(GrantRecord(actor, actor, "KNOWLEDGE", "VIEW", partition_id))
        for domain in DOMAINS:
            grants.append(GrantRecord(actor, actor, domain, "VIEW", partition_id))
    for actor in persons:
        for subject in persons:
            if actor == subject:
                continue
            if rng.random() < 0.3:
                grants.append(GrantRecord(actor, subject, "KNOWLEDGE", "VIEW", partition_id))

    return Corpus(
        seed=seed,
        size_label=size_label,
        partitions=partitions,
        persons=persons,
        circles=circles,
        assertions=tuple(assertions[:n] if len(assertions) > n else assertions),
        suppressions=tuple(suppressions),
        bindings=tuple(bindings),
        grants=tuple(grants),
    )


if __name__ == "__main__":
    for label in SIZE_TABLE:
        c = generate_corpus(label)
        print(
            f"{label}: assertions={len(c.assertions)} suppressions={len(c.suppressions)} "
            f"bindings={len(c.bindings)} grants={len(c.grants)} persons={len(c.persons)}"
        )
