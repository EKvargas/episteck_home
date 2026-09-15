"""Legacy Nutrition consent table retained for audit/migration only.

The Home Control Plane is the sole authorization authority. Nothing in this module
may grant access, and the table is not exposed through FastAPI or MCP.
"""
from __future__ import annotations


CONSENT_TABLE_DDL = """CREATE TABLE IF NOT EXISTS consent(
    person_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,          -- e.g. 'NUTRITION'
    state TEXT NOT NULL,          -- GRANTED | REVOKED
    granted_at TEXT,
    note TEXT
)"""
