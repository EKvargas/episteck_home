"""Explicit consent/reference state. Storing/processing a person's real Nutrition data
requires an explicit consent record. Household membership alone NEVER implies access.
Home Agent access is scoped to persons with an active consent record.
"""
from __future__ import annotations


CONSENT_TABLE_DDL = """CREATE TABLE IF NOT EXISTS consent(
    person_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,          -- e.g. 'NUTRITION'
    state TEXT NOT NULL,          -- GRANTED | REVOKED
    granted_at TEXT,
    note TEXT
)"""
