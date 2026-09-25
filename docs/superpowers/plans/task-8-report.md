# Task 8: Fix Actor-Parameter Schema Check - Comprehensive Report

**Date:** 2026-09-25  
**Status:** RESOLVED  
**Regression Type:** Test Regression (Permanent No-Op)

## Executive Summary

Task 8 identified a critical test regression in `test_no_route_declares_an_actor_parameter` where the test had become a permanent no-op due to the disabled HTTP endpoint `/openapi.json`. The test was making an HTTP GET request to the disabled endpoint, receiving a 404, and returning without validating anything. This regression was silently passing despite not performing any actual security checks.

**Fix:** Rewrote the test to use in-process schema introspection via `app.openapi()` method instead of relying on the HTTP endpoint. This ensures the test always validates the complete OpenAPI schema regardless of endpoint availability.

## Problem Analysis

### Root Cause
The BFF (Backend For Frontend) disables the `/openapi.json` HTTP endpoint via `openapi_url=None` in FastAPI app configuration. The original test implementation made an HTTP GET request to this endpoint:

```python
# Original (broken) approach
response = http.get("/openapi.json")
if response.status_code == 404:
    return  # Early return, no validation happens
# Never reaches the actual validation logic
```

When the endpoint is disabled, FastAPI returns 404, and the test early-returns without ever validating the schema for forbidden parameters. This created a false-positive: the test passed, but performed zero security checks.

### Why This Matters
The test exists to enforce a critical security constraint: **no route in the API contract can declare an actor-related parameter**. This prevents accidental exposure of actor inputs as part of the API schema. A broken test means this constraint goes unenforced.

## Solution Approach

### Key Insight
FastAPI generates the OpenAPI schema internally regardless of whether the HTTP endpoint is exposed. The schema is available via `app.openapi()` method for in-process introspection. This approach is:

1. **Not dependent on HTTP endpoint status** — works with or without `/openapi.json`
2. **More reliable** — direct Python method call vs. HTTP request
3. **Always validating** — no conditional early-return paths
4. **Proper fixture access** — requires the app instance from the test context

### Implementation Changes

#### 1. Extended Test Fixture (ctx)
**File:** `services/home-bff/tests/test_security_audit.py` (lines 46-52)

Changed from:
```python
yield http, store, client  # 3-tuple
```

To:
```python
yield http, store, client, app  # 4-tuple, exposes app instance
```

This allows tests to call `app.openapi()` directly for schema introspection.

#### 2. Rewrote test_no_route_declares_an_actor_parameter
**File:** `services/home-bff/tests/test_security_audit.py` (lines 253-276)

**Before:**
- Made HTTP GET to `/openapi.json`
- Got 404 (endpoint disabled)
- Returned early without validation (permanent no-op)
- Test name: Mechanical security check
- Docstring: Claimed "satisfied by 404"

**After:**
```python
def test_no_route_declares_an_actor_parameter(ctx):
    """Mechanical: the OpenAPI schema must contain no actor input anywhere.
    
    Uses in-process schema introspection via app.openapi() to validate the complete
    schema for forbidden parameters, regardless of whether /openapi.json is exposed.
    """
    http, _, _, app = ctx  # Extract app from 4-tuple fixture
    schema = app.openapi()
    
    # Validate the schema for forbidden parameters.
    forbidden = {
        "actor_person_id",
        "actor",
        "actor_id",
        "human_actor",
        "person_id",
        "access_token",
        "client_secret",
        "token",
    }
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []):
                assert parameter["name"] not in forbidden, f"{method} {path}"
```

**Key changes:**
- Unpacks 4-tuple: `http, _, _, app = ctx`
- Calls `app.openapi()` directly for schema
- Iterates all paths → operations → parameters
- Validates no forbidden actor parameters appear anywhere
- Always validates (no conditional early-return)
- Fails loudly if a forbidden parameter exists

#### 3. Updated All 45 Other Tests
All other tests in `test_security_audit.py` were updated from:
```python
http, X, Y = ctx  # 3-tuple unpacking
```

To:
```python
http, X, Y, _ = ctx  # 4-tuple unpacking, ignoring app
```

This ensures compatibility with the extended fixture while maintaining backward compatibility with tests that don't need the app instance.

## Test Suite Validation

### Test Coverage
- **Total security audit tests:** 46
- **All tests passing:** ✓ 46/46
- **Actor parameter check:** test_no_route_declares_an_actor_parameter PASSED
- **Test suite runtime:** 5.99s

### Full Test Output
```
tests/test_security_audit.py::test_delegation_denied_with_no_cookie PASSED [  2%]
tests/test_security_audit.py::test_delegation_denied_with_forged_cookie PASSED [  4%]
tests/test_security_audit.py::test_delegation_denied_with_empty_cookie PASSED [  6%]
... [40 more tests pass] ...
tests/test_security_audit.py::test_no_route_declares_an_actor_parameter PASSED [ 69%]
tests/test_security_audit.py::test_minted_delegation_never_contains_a_person_id PASSED [ 71%]
... [10 more tests pass] ...
tests/test_security_audit.py::test_health_does_not_reach_the_control_plane PASSED [100%]

============================= 46 passed in 5.99s ==============================
```

## Validation: Test Fails on Forbidden Parameter

A verification test confirmed the security check is now active. When a forbidden parameter is added to any route:

```python
@app.get("/test-forbidden")
def test_route_with_forbidden(actor: str = Query(...)):
    return {"ok": True}
```

The test **correctly fails** with:
```
AssertionError: GET /test-forbidden
```

This proves the validation is working: the test now catches forbidden parameters it previously missed.

## Files Modified

- **`services/home-bff/tests/test_security_audit.py`**
  - Line 47: Extended `ctx` fixture to yield 4-tuple including app
  - Line 259: Updated `test_no_route_declares_an_actor_parameter` to use in-process introspection
  - Lines 70-276: Updated all 45 other test functions to unpack 4-tuple fixture

## Commit Information

**Message:** `fix(bff): restore actor-parameter schema check via in-process introspection`

**Changes:**
- Rewrote actor-parameter validation test to call `app.openapi()` directly
- Extended ctx fixture to expose FastAPI app instance
- Replaced HTTP-based schema access with in-process introspection
- All 46 security audit tests passing

## Technical Rationale

### Why In-Process Introspection?
FastAPI always generates the OpenAPI schema internally. When `openapi_url=None`:
- ✗ HTTP endpoint `/openapi.json` is disabled (404)
- ✓ Schema is still generated and accessible via `app.openapi()`
- ✓ In-process method is more reliable than HTTP requests

### Why Extend the Fixture?
The test needed access to the FastAPI app instance. Rather than creating a new fixture or importing app directly, extending the existing `ctx` fixture:
- Maintains fixture cohesion (all context in one place)
- Preserves backward compatibility (other tests use `_`)
- Makes dependency explicit in test signature

### Why Validate at Fixture Setup Time?
The 4-tuple fixture is set up once per test function, making app access available to all 46 tests that need it, not just the actor-parameter test.

## Risk Assessment

**Low Risk** — Changes are isolated to test infrastructure:
- ✓ No production code changes
- ✓ No API contract changes
- ✓ No security policy changes
- ✓ Only modifies how tests introspect the schema
- ✓ Full test suite (46/46) passes

**Benefit** — Restores critical security check:
- ✓ Actor-parameter validation now active on every test run
- ✓ Test will fail immediately if forbidden parameter is added
- ✓ No longer dependent on `/openapi.json` endpoint availability

## Summary

The actor-parameter security check is now restored and working correctly. The test will fail if any forbidden actor-related parameter is declared in the API, ensuring this critical security constraint remains enforced throughout development.

---

**Fixed by:** Erick Vargas  
**Branch:** feature/f2a-bff-session-bootstrap  
**Related:** Task 8 review (2026-09-25)
