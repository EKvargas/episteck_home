"""bench keeps an app in sites/apps.txt only if it looks like a Frappe app.

bench (``bench.utils.is_frappe_app``) needs ``hooks.py``, ``modules.txt`` and
``patches.txt`` somewhere under the app folder. Without one of them, the next
``bench get-app`` or ``bench update`` rewrites ``sites/apps.txt`` without this app,
Frappe stops loading its hooks, and Home refuses every delegated call.
"""

from configparser import ConfigParser
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
BENCH_MARKERS = ("hooks.py", "modules.txt", "patches.txt")


def test_app_has_every_file_bench_uses_to_detect_a_frappe_app():
    missing = [name for name in BENCH_MARKERS if not list(APP.glob(f"**/{name}"))]
    assert missing == []


def test_patches_file_has_both_v15_sections():
    parser = ConfigParser(allow_no_value=True, delimiters="\n")
    parser.read(APP / "episteck_home" / "patches.txt")
    assert parser.sections() == ["pre_model_sync", "post_model_sync"]
