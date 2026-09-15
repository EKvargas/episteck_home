# ADR-0006: Family/Care graph (Person/Circle/CareRelationship)

## Status
Accepted (2026-09-15)

## Context
Households and care networks overlap: a person can be in multiple circles and have
multiple care relationships. We must model this without letting structure imply access.

## Decision
Model **Person** (Person ≠ User; may exist without login), **Circle**
(HOUSEHOLD/FAMILY/CARE/CUSTOM), **CircleMembership**, and **CareRelationship**
(CAREGIVER/COORDINATOR/GUARDIAN/FAMILY_SUPPORT). People may belong to multiple
overlapping circles.

## Consequences
+ Rich real-world modeling of families/care networks.
− Must be paired with strict consent: **membership and care relationship alone MUST
  NOT authorize sensitive-domain access** (see ADR-0008). This is a hard invariant.

## Alternatives
- Flat "household = shared access": rejected (unsafe; violates consent-first).
