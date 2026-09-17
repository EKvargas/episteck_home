"""Shared test environment for Home MCP.

``home_mcp.server`` builds a ``HomeControlPlaneClient`` at import time via
``from_env()``, so these variables must exist before any test module imports it.
They previously lived at the top of ``test_tool_contract.py``, which made every other
module depend on that one being imported first. A conftest applies to the package and
does not care about collection order.

The values are deliberately unreachable: no test in this suite may talk to a real
Control Plane.
"""
import os

os.environ.setdefault("HOME_CONTROL_PLANE_URL", "https://home.invalid")
os.environ.setdefault("HOME_API_KEY", "test-key")
os.environ.setdefault("HOME_API_SECRET", "test-secret")
