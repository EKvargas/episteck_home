from decimal import Decimal

import httpx
import pytest

from app.providers.nutrient_map import CANONICAL_UNITS
from app.providers.openfoodfacts import OpenFoodFactsProvider
from app.providers.usda import UsdaFoodProvider


def _client(payload):
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))


@pytest.fixture
def usda_stub():
    p = UsdaFoodProvider(api_key="k")
    p._c = _client({
        "fdcId": 123, "description": "Cola", "dataType": "Survey (FNDDS)",
        "foodCategory": {"description": "Beverages"},
        "foodPortions": [{"gramWeight": 248}, {"gramWeight": 100}],
        "foodNutrients": [
            {"nutrient": {"number": "269"}, "amount": 10.6},
            {"nutrient": {"number": "539"}, "amount": 10.6},
        ],
    })
    return p


def _off(nutriments_extra=None, **product):
    p = OpenFoodFactsProvider()
    nutr = {"sugars_100g": 10.6}
    nutr.update(nutriments_extra or {})
    body = {"product": {"product_name": "Cola", "nutriments": nutr,
                        "categories_tags": ["en:beverages", "en:carbonated-drinks", "en:sodas"], **product}}
    p._c = _client(body)
    return p


def test_canonical_units_include_sugars():
    assert CANONICAL_UNITS["sugars_total_g"] == "g"
    assert CANONICAL_UNITS["sugars_added_g"] == "g"


def test_usda_maps_total_and_added_sugars(usda_stub):
    rec = usda_stub.get_food("usda:123")
    assert rec.nutrients_per_100g["sugars_total_g"] == Decimal("10.6")
    assert rec.nutrients_per_100g["sugars_added_g"] == Decimal("10.6")
    assert rec.category == "Beverages"
    assert rec.serving_g == Decimal("248")
    assert rec.density_g_per_ml is None


def test_usda_serving_falls_back_to_serving_size_in_grams():
    p = UsdaFoodProvider(api_key="k")
    p._c = _client({"fdcId": 1, "description": "x", "servingSize": 30, "servingSizeUnit": "g",
                    "foodNutrients": []})
    rec = p.get_food("usda:1")
    assert rec.serving_g == Decimal("30")
    assert rec.category is None
    p._c = _client({"fdcId": 1, "description": "x", "servingSize": 30, "servingSizeUnit": "ml",
                    "foodNutrients": []})
    assert p.get_food("usda:1").serving_g is None


def test_off_maps_sugars_category_and_serving():
    rec = _off(serving_quantity=330, serving_quantity_unit="g").get_food("off:5449000000996")
    assert rec.nutrients_per_100g["sugars_total_g"] == Decimal("10.6")
    assert "sugars_added_g" not in rec.nutrients_per_100g
    assert rec.category == "en:beverages,en:carbonated-drinks,en:sodas"
    assert rec.serving_g == Decimal("330")


def test_off_serving_without_unit_is_grams():
    assert _off(serving_quantity="250").get_food("off:1").serving_g == Decimal("250")


def test_off_added_sugars_mapped():
    rec = _off({"added-sugars_100g": 4}).get_food("off:1")
    assert rec.nutrients_per_100g["sugars_added_g"] == Decimal("4")


def test_off_serving_in_ml_is_not_a_gram_serving():
    assert _off(serving_quantity=330, serving_quantity_unit="ml").get_food("off:1").serving_g is None


def test_usda_fndds_category_comes_from_the_wweia_food_group():
    p = UsdaFoodProvider(api_key="k")
    p._c = _client({
        "fdcId": 2707861, "description": "Cheesecake, plain", "dataType": "Survey (FNDDS)",
        "wweiaFoodCategory": {"wweiaFoodCategoryDescription": "Cakes and pies", "wweiaFoodCategoryCode": 3303270},
        "foodNutrients": [{"nutrient": {"number": "269"}, "amount": 26.6}],
    })
    rec = p.get_food("usda:2707861")
    assert rec.category == "Cakes and pies"
    assert rec.source == "USDA_FDC:Survey (FNDDS)"
