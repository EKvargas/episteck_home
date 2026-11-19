from decimal import Decimal

import pytest

from nutrition_domain.free_sugars import (
    FREE_SUGAR_MAP_VERSION,
    FreeSugarClass,
    classify,
    item_free_sugars_g,
)

FREE = FreeSugarClass.FREE
NOT_FREE = FreeSugarClass.NOT_FREE
UNKNOWN = FreeSugarClass.UNKNOWN


def test_version():
    assert FREE_SUGAR_MAP_VERSION == "episteck-fs-1"


def test_classify_examples():
    assert classify("OPEN_FOOD_FACTS", "en:beverages,en:carbonated-drinks,en:sodas") is FREE
    assert classify("OPEN_FOOD_FACTS", "en:fruit-juices") is FREE
    assert classify("OPEN_FOOD_FACTS", "en:flavoured-milks") is FREE
    assert classify("OPEN_FOOD_FACTS", "en:fresh-fruits") is NOT_FREE
    assert classify("OPEN_FOOD_FACTS", "en:milks") is NOT_FREE
    assert classify("USDA_FDC", "Sweets") is FREE
    assert classify("USDA_FDC", "Fruits and Fruit Juices") is UNKNOWN
    assert classify("OPEN_FOOD_FACTS", None) is UNKNOWN


def test_off_free_tag_wins_over_not_free_tag():
    assert classify("OPEN_FOOD_FACTS", "en:milks,en:flavoured-milks") is FREE
    assert classify("OPEN_FOOD_FACTS", "en:fresh-fruits,en:fruit-juices") is FREE


def test_off_tags_match_exactly_not_by_substring():
    assert classify("OPEN_FOOD_FACTS", "en:sodas-and-more") is UNKNOWN
    assert classify("OPEN_FOOD_FACTS", " en:milks , en:cheeses") is NOT_FREE
    assert classify("OPEN_FOOD_FACTS", "en:unlisted-thing") is UNKNOWN
    assert classify("OPEN_FOOD_FACTS", "") is UNKNOWN


def test_synthetic_uses_off_table():
    assert classify("SYNTHETIC", "en:sodas") is FREE
    assert classify("SYNTHETIC", "en:fresh-fruits") is NOT_FREE
    assert classify("SYNTHETIC", None) is UNKNOWN


def test_unknown_source_is_unknown():
    assert classify("MYSTERY", "Sweets") is UNKNOWN


def test_usda_table():
    assert classify("USDA_FDC", "Vegetables and Vegetable Products") is NOT_FREE
    assert classify("USDA_FDC", "Beverages") is UNKNOWN
    assert classify("USDA_FDC", None) is UNKNOWN
    assert classify("USDA_FDC", "Something else") is UNKNOWN


def test_name_is_ignored_for_other_sources():
    assert classify("USDA_FDC", "Sweets", name="Apfel roh") is FREE
    assert classify("OPEN_FOOD_FACTS", "en:milks", name="Orangensaft") is NOT_FREE


@pytest.mark.parametrize(
    "letter,name,expected",
    [
        ("F", "Apfel roh", NOT_FREE),
        ("F", "Nektarine roh", NOT_FREE),
        ("F", "Nektarine gedünstet", NOT_FREE),
        ("F", "Orangennektar", FREE),
        ("T", "Thunfisch im eigenen Saft, Konserve, abgetropft", NOT_FREE),
        ("T", "Makrele im eigenen Saft, Konserve, abgetropft", NOT_FREE),
        ("U", "Rindfleisch im eigenen Saft, mit Schweineschwarten, Konserve", NOT_FREE),
        ("U", "Schweinefleisch im eigenen Saft, mit Schwarten Konserve", NOT_FREE),
        ("U", "Rindfleisch in Gelee, Konserve", NOT_FREE),
        ("T", "Hering in Gelee (Kochfischware)", NOT_FREE),
        ("W", "Ochsenschwanz in Gelee", NOT_FREE),
        ("F", "Birne in Fruchtsaft, Konserve, abgetropft", FREE),
        ("F", "Orangensaft", FREE),
        ("F", "Smoothie purpur (Früchte)", FREE),
        ("F", "Pfirsich gezuckert, Konserve, abgetropft", FREE),
        ("F", "Honigmelone roh", NOT_FREE),
        ("F", None, NOT_FREE),
        ("M", "Vollmilch 3,5 % Fett", NOT_FREE),
        ("M", "Joghurt mild, mit Früchten", UNKNOWN),
        ("M", "Fruchtjoghurt", UNKNOWN),
        ("M", "Kondensmilch gesüßt", FREE),
        ("M", "Kakaomilch Schoko", FREE),
        ("S", "Blütenhonig", FREE),
        ("N", "Apfelsaft", FREE),
        ("X", "Gurkensalat", UNKNOWN),
        ("Y", "Vanilleeis", FREE),
        ("Y", "Pudding mit Milch", FREE),
        ("Y", "Reis mit Gemüse", UNKNOWN),
        ("U", "Eisbein gekocht", NOT_FREE),
        ("N", "Eistee ungesüßt", FREE),
        ("G", "Süßkartoffel roh", NOT_FREE),
        ("C", "Haferflocken", NOT_FREE),
        ("F", "Apfelmus ohne Zuckerzusatz", NOT_FREE),
        ("F", "Kirschen ungezuckert", NOT_FREE),
        ("F", "Süßkirsche roh", NOT_FREE),
        ("G", "Zuckermais, Konserve", NOT_FREE),
        ("D", "Honigkuchen", FREE),
        ("G", "Rucola roh", NOT_FREE),
        ("X", "Pfannkuchen ungesüßt, gebraten", UNKNOWN),
        ("P", "Colabier", FREE),
        ("X", "Kartoffelpuffer/Reibekuchen, gebraten", UNKNOWN),
        ("X", "Flammkuchen Elsässer Art", UNKNOWN),
        ("X", "Zwiebelkuchen ohne Speck", UNKNOWN),
        ("X", "Kartoffel-Gemüse-Kuchen", UNKNOWN),
        ("X", "Broccolicremesuppe mit Joghurt", UNKNOWN),
        ("X", "Gemüsesuppe püriert/Gemüsecremesuppe", UNKNOWN),
        ("X", "Toastschnitten mit Schinkencreme, gebacken", UNKNOWN),
        ("X", "Avocadocreme (Guacamole)", UNKNOWN),
        ("Y", "Vanillecremeeis", FREE),
        ("Y", "Bayerische Creme", FREE),
        ("Y", "Pfitzauf/Kuchenmichel, gebacken", FREE),
        ("Y", "Apfelkuchen", FREE),
        ("R", "Tomatenketchup", UNKNOWN),
        ("P", "Bier", UNKNOWN),
        ("Z", "Irgendwas", UNKNOWN),
        (None, "Apfelsaft", FREE),  # markers apply to any letter
        (None, "Vollkornbrot", UNKNOWN),
        ("", None, UNKNOWN),
        ("f", "Apfel roh", NOT_FREE),
    ],
)
def test_bls(letter, name, expected):
    assert classify("BLS", letter, name=name) is expected


def test_item_free_sugars():
    n = {"sugars_total_g": Decimal("10.6")}
    assert item_free_sugars_g(FREE, n, Decimal("330")) == Decimal("34.98")
    assert item_free_sugars_g(FREE, {}, Decimal("330")) is None
    assert item_free_sugars_g(NOT_FREE, n, Decimal("150")) == Decimal("0")
    assert item_free_sugars_g(NOT_FREE, {}, Decimal("150")) == Decimal("0")
    assert item_free_sugars_g(UNKNOWN, {"sugars_added_g": Decimal("5")}, Decimal("100")) == Decimal("5")
    assert item_free_sugars_g(UNKNOWN, n, Decimal("100")) is None


def test_usda_source_with_data_type_suffix():
    assert classify("USDA_FDC:Foundation", "Sweets") is FREE
    assert classify("USDA_FDC:SR Legacy", "Vegetables and Vegetable Products") is NOT_FREE
    assert classify("USDA_FDC:Branded", "Beverages") is UNKNOWN
