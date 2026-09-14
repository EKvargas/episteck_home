"""Repository abstraction — swap SQLite→Postgres later without touching API/domain."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class NutritionRepository(ABC):
    # profiles
    @abstractmethod
    def upsert_profile(self, person_id: str, profile: dict) -> dict: ...
    @abstractmethod
    def get_profile(self, person_id: str) -> dict | None: ...
    # intake (planned + actual kept distinct via 'kind')
    @abstractmethod
    def add_intake(self, person_id: str, record: dict) -> dict: ...
    @abstractmethod
    def list_intake(self, person_id: str, date: str, kind: str | None = None) -> list[dict]: ...
