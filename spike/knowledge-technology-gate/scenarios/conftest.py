"""Shared pytest fixtures for P1-P13 scenarios.

Runs each scenario against whichever backends are actually available (correction 12: no
scenario "fails the task" because Postgres is blocked -- it is parametrized only over
backends that could be constructed, and the report separately records the NOT EXECUTED
status for anything skipped here).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backends.postgres_env import detect_postgres  # noqa: E402
from backends.sqlite_backend import SQLiteKnowledgeBackend  # noqa: E402
from corpus.generator import generate_corpus  # noqa: E402


def _make_sqlite():
    return SQLiteKnowledgeBackend()


def _make_postgres():
    availability = detect_postgres()
    if not availability.available:
        pytest.skip(f"S1-PostgreSQL NOT EXECUTED - ENVIRONMENT BLOCKED: {availability.reason}")
    from backends.postgres_backend import PostgresKnowledgeBackend

    return PostgresKnowledgeBackend(availability.dsn)


BACKEND_FACTORIES = {
    "sqlite": _make_sqlite,
    "postgres": _make_postgres,
}


@pytest.fixture(params=["sqlite", "postgres"])
def backend(request):
    factory = BACKEND_FACTORIES[request.param]
    be = factory()
    yield be
    be.close()


@pytest.fixture
def small_corpus():
    return generate_corpus("C-small", seed=42)


@pytest.fixture
def loaded_backend(backend, small_corpus):
    backend.load_corpus(small_corpus)
    return backend, small_corpus
