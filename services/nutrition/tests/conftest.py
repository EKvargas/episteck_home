"""Shared test environment for the Nutrition service.

``app.mcp.server`` and ``app.main`` build a real service — including a
``HomeControlPlaneClient`` via ``from_env()`` — at IMPORT time, so these variables must
exist before any test module imports them.

The values are deliberately unreachable: no test in this suite may talk to a real
Control Plane or a real database.
"""
import os
import tempfile

import pytest

_DEFAULTS = {
    "HOME_CONTROL_PLANE_URL": "https://home.invalid",
    "HOME_API_KEY": "test-key",
    "HOME_API_SECRET": "test-secret",
    "FOOD_PROVIDER": "synthetic",
}

for _name, _value in _DEFAULTS.items():
    os.environ.setdefault(_name, _value)

# A scratch DB so an import-time build never touches a developer's real file.
os.environ.setdefault(
    "NUTRITION_DB", os.path.join(tempfile.gettempdir(), "episteck-nutrition-tests.sqlite")
)


@pytest.fixture
def nutrition_env():
    """Marks a test as depending on the import-time environment above.

    The variables are already set at module import — this fixture exists so the
    dependency is visible in the test signature rather than implicit.
    """
    return dict(_DEFAULTS)
