"""Episteck-owned adapter around the Mealie API. All Mealie access funnels here;
business logic never calls Mealie endpoints directly. Uses a dedicated API token
(never the admin password), read from the service secret. Loopback endpoint.
"""
from __future__ import annotations
import os
import httpx


class MealieAdapter:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.environ["MEALIE_BASE_URL"]).rstrip("/")
        self._token = token or os.environ["MEALIE_API_TOKEN"]
        self._client = httpx.Client(timeout=10.0,
                                    headers={"Authorization": f"Bearer {self._token}"})

    def _get(self, path, **params):
        r = self._client.get(f"{self.base_url}{path}", params=params); r.raise_for_status(); return r.json()

    def _post(self, path, json):
        r = self._client.post(f"{self.base_url}{path}", json=json); r.raise_for_status(); return r.json()

    def search_recipes(self, query: str) -> list[dict]:
        data = self._get("/api/recipes", search=query, perPage=25)
        return data.get("items", [])

    def get_recipe(self, slug: str) -> dict:
        return self._get(f"/api/recipes/{slug}")

    def get_meal_plan(self, start_date: str, end_date: str) -> list[dict]:
        data = self._get("/api/households/mealplans", start_date=start_date, end_date=end_date)
        return data.get("items", data if isinstance(data, list) else [])

    def add_meal_plan_entry(self, date: str, entry_type: str, recipe_id: str) -> dict:
        return self._post("/api/households/mealplans",
                          {"date": date, "entryType": entry_type, "recipeId": recipe_id})

    def get_shopping_lists(self) -> list[dict]:
        return self._get("/api/households/shopping/lists").get("items", [])
