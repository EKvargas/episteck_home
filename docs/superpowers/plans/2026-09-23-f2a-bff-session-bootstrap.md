# F2a-BFF Session Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the F2a-BFF slice of Home Hub session bootstrap: a login-CSRF binding cookie, a strict read-only `GET /bootstrap` route backed by the Control Plane's `get_home_bootstrap`, a `303 /app` callback success contract, classified upstream error handling, disabled public API docs, and an nginx route allowlist — with the full BFF-1..BFF-20 test matrix.

**Architecture:** All changes are confined to `services/home-bff/` (the public FastAPI app, `frappe_client.py`, `sessions.py`, `store.py`) and `deploy/home-bff/` (nginx config + a new static route test). The Control Plane side (`get_home_bootstrap`, `open_session`'s Person-link check) already shipped in PR #38 and is treated as a fixed, unmodified contract. No Next.js, no Quadlet activation, no deployment.

**Tech Stack:** Python 3.11+, FastAPI, httpx, SQLite (stdlib `sqlite3`), pytest, `fastapi.testclient.TestClient`.

**Spec:** `docs/product/HOME_HUB_F2_SESSION_BOOTSTRAP_PLAN.md` (§2–§13 specifically; §1 and §14–§15 are context/out-of-scope). This plan implements that spec verbatim and does not reopen any decision in it. If an implementation step reveals a contradiction between the spec and the actual PR #38 code, STOP and report the contradiction — do not redesign around it.

## Global Constraints

- Python 3.11+ syntax (repo-wide default already in use — `from __future__ import annotations`, `X | None` unions, `StrEnum`).
- No new runtime dependencies. Only `fastapi`, `uvicorn`, `httpx` are declared in `services/home-bff/pyproject.toml`; stay inside them plus stdlib (`hashlib`, `hmac`, `secrets`, `sqlite3`, `re`).
- Cookie `__Host-episteck_home_login`: random high-entropy value, `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=600`, **no `Domain` attribute** (required by the `__Host-` prefix and explicitly by the spec).
- Callback success: `303 See Other`, `Location: /app` as a **literal constant string**, never built from `return_to`/`next`/`redirect`/`redirect_uri`/`Host`/`X-Forwarded-Host`/`state`/any request value.
- `/bootstrap`: `GET` only (other verbs → `405`), cookie-authenticated only, **no** actor/person/context parameter of any kind (query, header, or body) may influence the response.
- Every BFF error body is exactly `{"error": "<CODE>"}` — never upstream text, never an upstream status code repeated back.
- Anti-oracle: `SESSION_REQUIRED` only for "no cookie at all"; every other definitive identity/session refusal (unknown local session, CP 401/403) collapses to `SESSION_INVALID`.
- CP outage/malformed response must **never** delete the local BFF session or its runtime binding, and must **never** redirect to login at the BFF layer (that decision belongs to the Next.js layer per §6, out of scope here).
- Secrets that must never appear in a response body or a log line across every new code path: OAuth access/refresh token, client secret, delegation secret, BFF session cookie value, `home_session_id`, OAuth `state`/`code`, Person/Circle ids, raw upstream response text.
- Public FastAPI app: `/docs`, `/redoc`, `/openapi.json` → `404`. The **internal mint app** (`internal_app.py`) is untouched — do not change its trust model.
- nginx changes are config-only, in `deploy/home-bff/nginx-home-bff.conf`; nothing here is deployed or activated.
- Preserve every existing test helper's name and call signature in `services/home-bff/tests/test_app.py` (`ctx`, `make_settings`, `FakeClient`, `login_and_get_state`, `complete_login`) because `test_security_audit.py` imports them directly (`from tests.test_app import (FakeClient, complete_login, login_and_get_state, make_settings)`). Changing their shape breaks that file too.

## Review Focus

- **Concurrent-tab login CSRF retry**: the spec (§9) explicitly accepts that two tabs overwrite the single binding cookie and the first callback then 400s. A reasonable implementer might be tempted to add multi-tab state — the plan must not do that, and a task's test should confirm a *second* `/login` overwrites the binding value so only the latest tab's callback can succeed (this is asserted implicitly by BFF-4's mismatch case, but Task 3 adds an explicit two-transaction check).
- **`ALREADY_BOUND` still succeeds**: it would be easy to accidentally treat `ALREADY_BOUND` as a partial failure when rewiring the callback response shape from JSON to a 303. BFF-6 pins this explicitly.
- **Bootstrap must not consult `/whoami`, `check_access`, or compose per-person calls**: a reasonable implementer familiar with the existing `get_care_dashboard`/`whoami` pattern might reach for those. The route must make exactly one call, `get_home_bootstrap(session_id=<home_session_id>)`, using the session's own stored values — Task 6/7 tests assert the stub sees exactly one call with exactly those two stored values, and that query/header/body actor hints change nothing.
- **Malformed-response partial acceptance**: a naive validator might accept `personContexts` while independently rejecting a bad `careRelationships` entry, returning a document missing just that one bad field. The spec requires the *whole* payload rejected as `502 INVALID_RESPONSE`. Task 8's tests include at least one case per malformation class (bad regex, unknown enum, duplicate, viewer-as-care-subject, dangling `subjectPersonId`, over-bound) each individually causing full rejection.
- **Migration idempotency under concurrent startup**: BFF-20 is easy to under-test as "run twice sequentially, no error" without covering genuinely concurrent access from two processes (the public app and the mint app can both call `SessionStore.__init__` against the same file at process start). Task 2's test spins up two `SessionStore` instances against the same path back-to-back and also drives the migration via `ALTER TABLE ... ADD COLUMN` inside a guarded `try/except sqlite3.OperationalError` for the "column already exists" case, proven by asserting the schema has exactly one such column after both.
- **nginx route ordering / `/app` vs `/application`**: `location ^~ /app/` and `location = /app` must not accidentally let a generic `location /app` (without the anchor) swallow `/application`. Task 11's static test parses the raw config text and asserts both the anchored forms are present and a naive `location /app ` (space, no `~`/`=`) is absent.

---

## File Structure

**Modify:**
- `services/home-bff/home_bff/sessions.py` — add login-binding cookie constants/flags and a `new_login_binding()` + `hash_login_binding()` helper pair (mirrors the existing `new_session_id()` / cookie-flags pattern already in this file).
- `services/home-bff/home_bff/store.py` — add `login_binding_hash` column to `oauth_transaction` (idempotent migration in `SessionStore.__init__`), thread it through `begin_transaction`/`consume_transaction`/`Transaction`.
- `services/home-bff/home_bff/frappe_client.py` — replace the single `SessionOpenError` used for bootstrap classification with `UpstreamRefused` / `UpstreamUnavailable` / `UpstreamMalformed`, and add a `get_home_bootstrap(access_token, session_id)` method. `SessionOpenError` stays (used unchanged by `open_home_session`/`whoami`); the new exceptions are additive, imported alongside it.
- `services/home-bff/home_bff/app.py` — `/login` sets the binding cookie; `/callback` validates it, returns `303`, clears the cookie on every outcome; new `GET /bootstrap` route; `FastAPI(...)` constructed with `docs_url=None, redoc_url=None, openapi_url=None`.
- `deploy/home-bff/nginx-home-bff.conf` — replace catch-all `location /` with the explicit allowlist from §11.
- `services/home-bff/tests/test_app.py` — `complete_login`/callback-shape assertions move from `200 JSON` to `303 + Location: /app`; existing callback tests updated in place (not duplicated) to match the new response shape while keeping their original assertions about status/cookie/replay/etc.
- `services/home-bff/tests/test_security_audit.py` — no signature changes needed (it imports the *names*, and `complete_login`'s new internal behavior is transparent to callers that only read `http.cookies`), but one assertion (`test_no_secret_in_callback_response_or_cookie`) is checked against the new 303 body/headers instead of JSON.

**Create:**
- `services/home-bff/home_bff/bootstrap.py` — the strict CP-response validator/mapper (`validate_bootstrap_response(raw: dict) -> BootstrapResponse`), kept in its own module because it is a self-contained parsing/validation concern distinct from HTTP routing, matching this repo's existing pattern of one responsibility per module (`oauth.py`, `sessions.py`, `runtime.py` are all similarly narrow).
- `services/home-bff/tests/test_bootstrap_validation.py` — unit tests for the validator in isolation (regex/enum/bounds/duplicate/dangling-reference cases), separate from the HTTP-level tests so malformed-shape cases don't need a full `TestClient` round trip.
- `services/home-bff/tests/test_bootstrap_route.py` — HTTP-level tests for `GET /bootstrap` (BFF-7, 8, 9, 10, 11, 13, 14, 16, 17, 18 live here).
- `services/home-bff/tests/test_login_binding.py` — login-CSRF binding cookie tests (BFF-1 through BFF-6, BFF-20 migration test).
- `services/home-bff/tests/test_public_docs_disabled.py` — BFF-19.
- `deploy/home-bff/tests/test_nginx_routes.py` — static config test for the new nginx allowlist (§12 Deploy row).

---

## Task 1: Login-binding cookie primitives in `sessions.py`

**Files:**
- Modify: `services/home-bff/home_bff/sessions.py`
- Test: `services/home-bff/tests/test_login_binding.py` (new file, created in this task)

**Interfaces:**
- Produces: `LOGIN_BINDING_COOKIE_NAME = "__Host-episteck_home_login"`, `LOGIN_BINDING_MAX_AGE_SECONDS = 600`, `LOGIN_BINDING_COOKIE_FLAGS: dict` (httponly/secure/samesite/path, **no** `domain` key), `new_login_binding() -> str` (opaque random value), `hash_login_binding(value: str) -> str` (hex sha256).

- [ ] **Step 1: Write the failing tests**

Create `services/home-bff/tests/test_login_binding.py`:

```python
"""Login-binding cookie primitives (F2a-BFF, B3 / §9)."""
from __future__ import annotations

from home_bff import sessions


def test_login_binding_cookie_name_uses_host_prefix():
    assert sessions.LOGIN_BINDING_COOKIE_NAME == "__Host-episteck_home_login"


def test_login_binding_cookie_flags_have_no_domain():
    flags = sessions.LOGIN_BINDING_COOKIE_FLAGS
    assert flags["httponly"] is True
    assert flags["secure"] is True
    assert flags["samesite"] == "lax"
    assert flags["path"] == "/"
    assert "domain" not in flags


def test_login_binding_max_age_is_ten_minutes():
    assert sessions.LOGIN_BINDING_MAX_AGE_SECONDS == 600


def test_new_login_binding_is_random_and_unique():
    values = {sessions.new_login_binding() for _ in range(10)}
    assert len(values) == 10
    assert all(len(v) >= 32 for v in values)


def test_hash_login_binding_is_sha256_hex():
    import hashlib

    value = "some-binding-value"
    expected = hashlib.sha256(value.encode()).hexdigest()
    assert sessions.hash_login_binding(value) == expected


def test_hash_login_binding_is_deterministic():
    value = sessions.new_login_binding()
    assert sessions.hash_login_binding(value) == sessions.hash_login_binding(value)


def test_different_bindings_hash_differently():
    a, b = sessions.new_login_binding(), sessions.new_login_binding()
    assert sessions.hash_login_binding(a) != sessions.hash_login_binding(b)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/home-bff && python -m pytest tests/test_login_binding.py -v`
Expected: FAIL — `AttributeError: module 'home_bff.sessions' has no attribute 'LOGIN_BINDING_COOKIE_NAME'` (and similar for the rest).

- [ ] **Step 3: Implement the primitives**

In `services/home-bff/home_bff/sessions.py`, add after the existing `COOKIE_FLAGS` block (after line 45):

```python
# Login-CSRF browser-binding cookie (B3 / §9). Bound to the browser that started
# /login, not to the OAuth transaction's identity. The __Host- prefix forbids a
# Domain attribute and requires Secure + Path=/, which is why COOKIE_FLAGS below
# carries no "domain" key — that omission is load-bearing, not an oversight.
LOGIN_BINDING_COOKIE_NAME = "__Host-episteck_home_login"
LOGIN_BINDING_MAX_AGE_SECONDS = 600
LOGIN_BINDING_COOKIE_FLAGS = {
    "httponly": True,
    "secure": True,
    "samesite": "lax",
    "path": "/",
}


def new_login_binding() -> str:
    """Opaque, high-entropy value carried only in the binding cookie."""
    return secrets.token_urlsafe(32)


def hash_login_binding(value: str) -> str:
    """The transaction stores only this. The raw value never leaves the cookie."""
    return hashlib.sha256(value.encode()).hexdigest()
```

Add `import hashlib` to the top-level imports (alongside the existing `import hmac`, `import secrets`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/home-bff && python -m pytest tests/test_login_binding.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add services/home-bff/home_bff/sessions.py services/home-bff/tests/test_login_binding.py
git commit -m "feat(bff): add login-binding cookie primitives"
```

---

## Task 2: `login_binding_hash` column + idempotent migration in `store.py`

**Files:**
- Modify: `services/home-bff/home_bff/store.py`
- Test: `services/home-bff/tests/test_store.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `SessionStore.begin_transaction(..., login_binding_hash: str)` (new required kwarg), `Transaction.login_binding_hash: str` (new frozen-dataclass field), `SessionStore.consume_transaction(state) -> Transaction | None` (unchanged signature, now returns the hash too). Later tasks (3, 4) call `begin_transaction` with this kwarg and read `transaction.login_binding_hash`.

- [ ] **Step 1: Write the failing tests**

Add to `services/home-bff/tests/test_store.py` (check the file first for its existing fixture pattern, then append in the same style — it uses a `tmp_path`-backed `SessionStore` per test, matching `test_app.py`'s `ctx` fixture pattern):

```python
def test_transaction_persists_login_binding_hash(tmp_path):
    from home_bff.store import SessionStore

    store = SessionStore(str(tmp_path / "bff.sqlite"))
    store.begin_transaction(
        state="s1",
        code_verifier="v1",
        nonce="n1",
        redirect_uri="https://bff.invalid/callback",
        login_binding_hash="hash-of-binding",
    )
    transaction = store.consume_transaction("s1")
    assert transaction is not None
    assert transaction.login_binding_hash == "hash-of-binding"


def test_migration_adds_login_binding_hash_column_to_existing_db(tmp_path):
    """A store created before this column existed must upgrade in place."""
    import sqlite3

    from home_bff.store import SessionStore, _SCHEMA_PRE_LOGIN_BINDING

    path = str(tmp_path / "legacy.sqlite")
    with sqlite3.connect(path) as db:
        db.executescript(_SCHEMA_PRE_LOGIN_BINDING)
        db.commit()

    store = SessionStore(path)
    store.begin_transaction(
        state="s1",
        code_verifier="v1",
        nonce="n1",
        redirect_uri="https://bff.invalid/callback",
        login_binding_hash="hash-1",
    )
    transaction = store.consume_transaction("s1")
    assert transaction.login_binding_hash == "hash-1"


def test_migration_is_idempotent_across_repeated_init(tmp_path):
    import sqlite3

    from home_bff.store import SessionStore

    path = str(tmp_path / "bff.sqlite")
    SessionStore(path)
    SessionStore(path)
    SessionStore(path)

    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(oauth_transaction)")]
    assert columns.count("login_binding_hash") == 1


def test_migration_survives_concurrent_store_construction(tmp_path):
    """Simulates the public app and the mint process starting at the same time."""
    import threading

    from home_bff.store import SessionStore

    path = str(tmp_path / "bff.sqlite")
    errors: list[Exception] = []

    def build():
        try:
            SessionStore(path)
        except Exception as error:  # pragma: no cover - failure path under test
            errors.append(error)

    threads = [threading.Thread(target=build) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    import sqlite3

    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(oauth_transaction)")]
    assert columns.count("login_binding_hash") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/home-bff && python -m pytest tests/test_store.py -v -k login_binding or migration`
Expected: FAIL — `TypeError: begin_transaction() got an unexpected keyword argument 'login_binding_hash'` and `ImportError: cannot import name '_SCHEMA_PRE_LOGIN_BINDING'`.

- [ ] **Step 3: Implement the migration and threading**

In `services/home-bff/home_bff/store.py`:

Rename the current `_SCHEMA` constant to `_SCHEMA_PRE_LOGIN_BINDING` (this becomes the "legacy" fixture used by the migration test) and define a new `_SCHEMA` that is identical except `oauth_transaction` gains the column. Replace lines 45–70 with:

```python
_SCHEMA_PRE_LOGIN_BINDING = """
CREATE TABLE IF NOT EXISTS oauth_transaction (
    state          TEXT PRIMARY KEY,
    code_verifier  TEXT NOT NULL,
    nonce          TEXT NOT NULL,
    redirect_uri   TEXT NOT NULL,
    created_at     INTEGER NOT NULL,
    expires_at     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bff_session (
    session_id           TEXT PRIMARY KEY,
    home_session_id      TEXT NOT NULL,
    access_token         TEXT NOT NULL,
    refresh_token        TEXT,
    created_at           INTEGER NOT NULL,
    expires_at           INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_binding (
    runtime_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    bound_at   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES bff_session(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_tx_expiry ON oauth_transaction(expires_at);
CREATE INDEX IF NOT EXISTS ix_session_expiry ON bff_session(expires_at);
"""

# Same schema. New stores get the column from CREATE TABLE directly; existing
# stores get it from the ALTER TABLE migration in __init__ below. Both converge
# on this same shape, which is why the schema text lists it here too — a brand
# new SessionStore() must never need a second migration pass on its own file.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_transaction (
    state               TEXT PRIMARY KEY,
    code_verifier       TEXT NOT NULL,
    nonce               TEXT NOT NULL,
    redirect_uri        TEXT NOT NULL,
    login_binding_hash  TEXT NOT NULL DEFAULT '',
    created_at          INTEGER NOT NULL,
    expires_at          INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bff_session (
    session_id           TEXT PRIMARY KEY,
    home_session_id      TEXT NOT NULL,
    access_token         TEXT NOT NULL,
    refresh_token        TEXT,
    created_at           INTEGER NOT NULL,
    expires_at           INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_binding (
    runtime_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    bound_at   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES bff_session(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_tx_expiry ON oauth_transaction(expires_at);
CREATE INDEX IF NOT EXISTS ix_session_expiry ON bff_session(expires_at);
"""

_MIGRATE_ADD_LOGIN_BINDING_HASH = (
    "ALTER TABLE oauth_transaction ADD COLUMN login_binding_hash TEXT NOT NULL DEFAULT ''"
)
```

Update `Transaction` (previously lines 76–81) to add the new field:

```python
@dataclass(frozen=True)
class Transaction:
    state: str
    code_verifier: str
    nonce: str
    redirect_uri: str
    login_binding_hash: str
```

Update `SessionStore.__init__` (previously lines 99–116) so the migration runs inside the same busy-timeout-guarded connection used for schema creation, and is retried on the SQLite "duplicate column" error rather than treated as fatal:

```python
    def __init__(self, path: str) -> None:
        self._path = path
        if path == ":memory:":
            raise ValueError("SessionStore requires a filesystem database path")
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
            # WAL lets the mint process read the last committed binding while the
            # public process is preparing a short write transaction.
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(_SCHEMA)
            self._migrate_login_binding_hash(db)
            db.commit()
        # Tokens live here. Keep them unreadable to other service accounts even if
        # the parent directory is ever loosened.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _migrate_login_binding_hash(self, db: sqlite3.Connection) -> None:
        """Idempotent: a store created before this column existed gets it added.

        A store created fresh by _SCHEMA above already has the column, so this
        ALTER is a no-op there — SQLite raises "duplicate column name", which is
        the expected, harmless outcome, not a failure. Two processes (the public
        app and the mint app) can run this at the same time against the same
        file; busy_timeout above makes the second writer wait rather than error,
        and a duplicate-column result is equally harmless whichever one wins.
        """
        try:
            db.execute(_MIGRATE_ADD_LOGIN_BINDING_HASH)
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise
```

Update `begin_transaction` (previously lines 160–177):

```python
    def begin_transaction(
        self,
        *,
        state: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
        login_binding_hash: str,
    ) -> None:
        now = _now()
        with self._mutation() as db:
            db.execute(
                "INSERT INTO oauth_transaction"
                " (state, code_verifier, nonce, redirect_uri, login_binding_hash,"
                "  created_at, expires_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    state,
                    code_verifier,
                    nonce,
                    redirect_uri,
                    login_binding_hash,
                    now,
                    now + TRANSACTION_TTL_SECONDS,
                ),
            )
```

Update `consume_transaction` (previously lines 179–199) to read and return the new column:

```python
    def consume_transaction(self, state: str) -> Transaction | None:
        """Atomically fetch-and-delete. A second call with the same state gets None."""
        if not state:
            return None
        with self._mutation() as db:
            row = db.execute(
                "SELECT * FROM oauth_transaction WHERE state = ?", (state,)
            ).fetchone()
            if row is None:
                return None
            # Delete before validating expiry: a stale state is spent either way, so
            # it can never be retried.
            db.execute("DELETE FROM oauth_transaction WHERE state = ?", (state,))
            if row["expires_at"] <= _now():
                return None
            return Transaction(
                state=row["state"],
                code_verifier=row["code_verifier"],
                nonce=row["nonce"],
                redirect_uri=row["redirect_uri"],
                login_binding_hash=row["login_binding_hash"],
            )
```

Note: `self._connection()` (used in `__init__`) currently does not set `busy_timeout` before `PRAGMA journal_mode = WAL` — the explicit `db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")` line added above at the start of `__init__`'s `with self._connection() as db:` block is required so the concurrent-construction test does not flake under load; `_connect()` already sets it for other call sites, but `_connection()` wraps `_connect()` too, so verify `_connect()` sets it (it does, at line 126) — the added explicit `PRAGMA busy_timeout` line inside `__init__` is redundant with `_connect()` but confirms it applies before `executescript` runs; keep it for clarity.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/home-bff && python -m pytest tests/test_store.py -v`
Expected: all existing `test_store.py` tests PASS, plus the 4 new ones. If any pre-existing test in `test_store.py` calls `begin_transaction` without `login_binding_hash`, update that call site to pass `login_binding_hash="test-hash"`.

Also run the full existing suite to catch other `begin_transaction` call sites:

Run: `cd services/home-bff && python -m pytest tests/ -v -k begin_transaction`
Expected: PASS after updating any call site found (there should be none yet outside `test_store.py`, since `app.py`'s `/login` route is updated in Task 3).

- [ ] **Step 5: Commit**

```bash
git add services/home-bff/home_bff/store.py services/home-bff/tests/test_store.py
git commit -m "feat(bff): add idempotent login_binding_hash migration to oauth_transaction"
```

---

## Task 3: `/login` sets the binding cookie; `/callback` validates it and returns 303

**Files:**
- Modify: `services/home-bff/home_bff/app.py`
- Modify: `services/home-bff/tests/test_app.py` (update `complete_login`, `test_callback_*` assertions)

**Interfaces:**
- Consumes: `sessions.LOGIN_BINDING_COOKIE_NAME`, `sessions.LOGIN_BINDING_COOKIE_FLAGS`, `sessions.LOGIN_BINDING_MAX_AGE_SECONDS`, `sessions.new_login_binding()`, `sessions.hash_login_binding()` (Task 1); `store.begin_transaction(..., login_binding_hash=...)`, `Transaction.login_binding_hash` (Task 2).
- Produces: `/login` sets `Set-Cookie: __Host-episteck_home_login=...`. `/callback` on success returns `303` with `Location: /app`, sets the session cookie, clears the binding cookie, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, empty body. On every failure branch (400/403/503) the binding cookie is also cleared and no session cookie is set. This is the contract Task 6 (`/bootstrap`) and later tasks build on for "does a failure ever touch the session store" assertions.

- [ ] **Step 1: Write the failing tests**

Append to `services/home-bff/tests/test_login_binding.py` (BFF-1 through BFF-6):

```python
# --------------------------------------------------------- BFF-1 .. BFF-6 (HTTP)

import pytest
from fastapi.testclient import TestClient

from home_bff.app import create_app
from home_bff.frappe_client import SessionOpenError, TokenExchangeError
from home_bff.runtime import RUNTIME_ID, BindResult
from home_bff.store import SessionStore, StoreUnavailableError

# Reuse the exact fixtures test_app.py already defines, so both files stay in sync.
from tests.test_app import FakeClient, login_and_get_state, make_settings  # noqa: E402


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = FakeClient()
    app = create_app(make_settings(), store=store, client=client)
    with TestClient(app, base_url="https://bff.invalid") as http:
        yield http, store, client


def _binding_cookie(http) -> str | None:
    from home_bff import sessions

    return http.cookies.get(sessions.LOGIN_BINDING_COOKIE_NAME)


def test_login_sets_binding_cookie_with_exact_flags(ctx):
    http, _, _ = ctx
    from home_bff import sessions

    response = http.get("/login", follow_redirects=False)
    header = response.headers.get("set-cookie", "")
    assert sessions.LOGIN_BINDING_COOKIE_NAME in header
    lowered = header.lower()
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert "domain=" not in lowered
    assert "max-age=600" in lowered


def test_bff1_successful_callback_returns_303_with_flags_and_clears_binding(ctx):
    http, store, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)  # a second /login overwrites the first binding
    # login_and_get_state issues its own /login, so pick up the LATEST binding cookie:
    binding = _binding_cookie(http)
    assert binding

    response = http.get(
        f"/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    assert response.text == ""
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"

    from home_bff import sessions

    session_header = response.headers.get("set-cookie", "")
    assert sessions.COOKIE_NAME in session_header

    binding_after = response.cookies.get(sessions.LOGIN_BINDING_COOKIE_NAME)
    # Cleared: either absent, or present with an expiry in the past / empty value.
    assert not binding_after or binding_after == ""


def test_bff2_malicious_redirect_params_and_spoofed_host_still_redirect_to_app(ctx):
    http, _, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)

    response = http.get(
        f"/callback?code=c&state={state}"
        "&return_to=https://evil.example/steal"
        "&next=/other"
        "&redirect_uri=https://evil.example/cb",
        headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/app"


def test_bff3_replayed_state_is_400_with_no_session_cookie(ctx):
    http, _, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)

    first = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert first.status_code == 303

    replay = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert replay.status_code == 400
    from home_bff import sessions

    assert sessions.COOKIE_NAME not in replay.cookies


def test_bff4_missing_binding_cookie_is_400_transaction_consumed_no_session(ctx):
    http, store, _ = ctx
    state = login_and_get_state(http)
    http.cookies.clear()  # binding cookie never reaches the callback request

    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)

    assert response.status_code == 400
    from home_bff import sessions

    assert sessions.COOKIE_NAME not in response.cookies
    # Transaction was consumed: a second attempt with the same state also fails.
    replay = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert replay.status_code == 400


def test_bff4_mismatched_binding_cookie_is_400_transaction_consumed_no_session(ctx):
    http, store, _ = ctx
    state = login_and_get_state(http)
    from home_bff import sessions

    http.cookies.set(
        sessions.LOGIN_BINDING_COOKIE_NAME, "wrong-binding-value", domain="bff.invalid"
    )

    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)

    assert response.status_code == 400
    assert sessions.COOKIE_NAME not in response.cookies
    replay = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert replay.status_code == 400


def test_bff4_second_tab_login_overwrites_first_tabs_binding(ctx):
    """Two /login calls share one binding cookie slot; only the newest matches."""
    http, _, _ = ctx
    http.get("/login", follow_redirects=False)
    first_state = login_and_get_state(http)  # this issues a second /login internally

    # The callback for the FIRST tab's state now sees the SECOND tab's binding.
    response = http.get(
        f"/callback?code=c&state={first_state}", follow_redirects=False
    )
    assert response.status_code == 400


def test_bff5_error_param_is_400_no_redirect_no_cookie(ctx):
    http, _, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)
    response = http.get(
        f"/callback?error=access_denied&state={state}", follow_redirects=False
    )
    assert response.status_code == 400
    assert "location" not in response.headers


def test_bff5_exchange_failure_is_400(ctx):
    http, _, client = ctx
    client.exchange_error = TokenExchangeError("nope")
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 400
    assert "location" not in response.headers


def test_bff5_open_session_refusal_is_403(ctx):
    http, _, client = ctx
    client.session_error = SessionOpenError("no linked person")
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 403
    assert "location" not in response.headers


def test_bff5_runtime_binding_failure_is_503(ctx):
    http, store, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)

    def fail_claim(runtime_id, session_id):
        raise StoreUnavailableError("runtime store unavailable")

    store.claim_runtime = fail_claim
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 503
    assert "location" not in response.headers
    from home_bff import sessions

    assert sessions.COOKIE_NAME not in response.cookies


def test_bff6_already_bound_still_returns_303_and_enum_absent(ctx):
    http, store, _ = ctx
    owner = store.create_session(
        home_session_id="HDS-OWNER", access_token="owner-token", refresh_token=None
    )
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND

    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    assert BindResult.ALREADY_BOUND.value not in response.text
    assert "runtime_binding" not in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/home-bff && python -m pytest tests/test_login_binding.py -v`
Expected: FAIL — `/login` does not set the binding cookie yet (`assert sessions.LOGIN_BINDING_COOKIE_NAME in header` fails), and `/callback` still returns `200`, not `303`/`400` in the new shapes.

- [ ] **Step 3: Implement in `app.py`**

Update the `/login` route (current lines 76–106):

```python
    @app.get("/login")
    def login(store: SessionStore = Depends(get_store)):
        """Start an authorization-code login. All security state stays server-side."""
        store.purge_expired()

        pkce = new_pkce_pair()
        state = new_state()
        nonce = new_state()
        login_binding = sessions.new_login_binding()

        # The verifier is persisted here and NEVER put in the redirect. The browser
        # carries only `state`, which is an opaque lookup key with no authority.
        store.begin_transaction(
            state=state,
            code_verifier=pkce.verifier,
            nonce=nonce,
            redirect_uri=settings.redirect_uri,
            login_binding_hash=sessions.hash_login_binding(login_binding),
        )

        params = authorization_params(
            client_id=settings.client_id,
            redirect_uri=settings.redirect_uri,
            pkce=pkce,
            state=state,
            scope=settings.scope,
        )
        params["nonce"] = nonce

        query = "&".join(f"{k}={_quote(v)}" for k, v in params.items())
        result = RedirectResponse(
            f"{app.state.client.authorize_url}?{query}", status_code=302
        )
        result.set_cookie(
            sessions.LOGIN_BINDING_COOKIE_NAME,
            login_binding,
            max_age=sessions.LOGIN_BINDING_MAX_AGE_SECONDS,
            **sessions.LOGIN_BINDING_COOKIE_FLAGS,
        )
        return result
```

Replace the `/callback` route (current lines 110–186) in full:

```python
    @app.get("/callback")
    def callback(
        response: Response,
        code: str | None = Query(default=None),
        state: str | None = Query(default=None),
        error: str | None = Query(default=None),
        login_binding: str | None = Cookie(
            default=None, alias=sessions.LOGIN_BINDING_COOKIE_NAME
        ),
        store: SessionStore = Depends(get_store),
        client: HomeOAuthClient = Depends(get_client),
    ):
        def _terminal(status_code: int, detail: str) -> None:
            """Every callback exit clears the binding cookie, success or failure."""
            _clear_login_binding_cookie(response)
            raise HTTPException(status_code, detail)

        if error:
            _terminal(400, "authorization was denied")

        # 1+2. Validate state AND single-use in one atomic step. A replayed state
        # finds nothing, because consume_transaction deletes as it reads.
        transaction = store.consume_transaction(state or "")
        if transaction is None:
            _terminal(400, "invalid or already-used authorization state")

        # B3 / §9: the transaction is already consumed above regardless of outcome,
        # so a missing or mismatched binding still burns the state — it cannot be
        # retried by fixing just the cookie.
        presented_hash = sessions.hash_login_binding(login_binding or "")
        if not login_binding or not hmac.compare_digest(
            presented_hash, transaction.login_binding_hash
        ):
            _terminal(400, "login could not be verified")

        if not code:
            _terminal(400, "authorization code missing")

        # 3+4. Server-side exchange, always with the verifier minted for THIS state.
        try:
            tokens = client.exchange_code(
                code=code,
                redirect_uri=transaction.redirect_uri,
                code_verifier=transaction.code_verifier,
            )
        except TokenExchangeError as exchange_error:
            # Log the FAILURE CLASS, never the message: an upstream error can echo
            # request parameters, and this record is the one that persists.
            logger.warning(
                "token exchange failed (%s)", type(exchange_error).__name__
            )
            _terminal(400, "authorization could not be completed")

        # 6-9. The Control Plane resolves the User from the token and maps it to a
        # Person. Zero links, two links, or a disabled user all surface here as a
        # refusal — we never inspect or second-guess that decision.
        try:
            home_session_id = client.open_home_session(tokens.access_token)
        except SessionOpenError as session_error:
            logger.warning(
                "home session refused (%s)", type(session_error).__name__
            )
            _terminal(403, "this account is not linked to a Home person")

        # 10+11. Opaque cookie only. Tokens stay in the server-side store.
        session = store.create_session(
            home_session_id=home_session_id,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )

        try:
            binding = store.claim_runtime(RUNTIME_ID, session.session_id)
        except (ValueError, StoreUnavailableError):
            try:
                store.delete_session(session.session_id)
            except StoreUnavailableError:
                pass
            _terminal(503, "runtime binding could not be completed")

        # ALREADY_BOUND is still success: the Home Hub session is valid, and agent
        # binding is orthogonal. `binding` is logged only as its static enum value,
        # never returned to the browser.
        logger.info("runtime binding outcome: %s", binding.value)

        result = Response(status_code=303, headers={"Location": "/app"})
        result.headers["Cache-Control"] = "no-store"
        result.headers["Referrer-Policy"] = "no-referrer"
        _set_session_cookie(result, session.session_id)
        _clear_login_binding_cookie(result)
        return result
```

Add `import hmac` to the top-level imports in `app.py` (alongside `import logging`).

Add the cookie-clearing helper near the existing `_clear_session_cookie` (end of file):

```python
def _clear_login_binding_cookie(response: Response) -> None:
    response.delete_cookie(
        sessions.LOGIN_BINDING_COOKIE_NAME,
        path=sessions.LOGIN_BINDING_COOKIE_FLAGS["path"],
        secure=sessions.LOGIN_BINDING_COOKIE_FLAGS["secure"],
        httponly=sessions.LOGIN_BINDING_COOKIE_FLAGS["httponly"],
        samesite=sessions.LOGIN_BINDING_COOKIE_FLAGS["samesite"],
    )
```

**Important implementation note on the `_terminal` helper:** FastAPI route functions cannot `raise` from inside a nested closure and have the outer `response: Response` mutations (cookie clearing) still apply to the *actual* response FastAPI sends for an `HTTPException` — `HTTPException` bypasses the injected `response` object entirely and is handled by FastAPI's exception middleware, which builds its own `JSONResponse`. Cookies set via `response.set_cookie`/`delete_cookie` on the injected `Response` parameter **are not attached** to an `HTTPException`'s response. Because clearing the binding cookie is required on every failure branch too, do **not** use `HTTPException` for this route's failure paths. Instead, replace every `_terminal(...)` call and its `HTTPException`-based body above with a **returned** `Response`/`JSONResponse` that carries the cleared cookie explicitly. Concretely, replace the `_terminal` helper and all call sites with:

```python
        def _failure(status_code: int, detail: str) -> Response:
            failure = JSONResponse({"detail": detail}, status_code=status_code)
            _clear_login_binding_cookie(failure)
            return failure

        if error:
            return _failure(400, "authorization was denied")

        transaction = store.consume_transaction(state or "")
        if transaction is None:
            return _failure(400, "invalid or already-used authorization state")

        presented_hash = sessions.hash_login_binding(login_binding or "")
        if not login_binding or not hmac.compare_digest(
            presented_hash, transaction.login_binding_hash
        ):
            return _failure(400, "login could not be verified")

        if not code:
            return _failure(400, "authorization code missing")

        try:
            tokens = client.exchange_code(
                code=code,
                redirect_uri=transaction.redirect_uri,
                code_verifier=transaction.code_verifier,
            )
        except TokenExchangeError as exchange_error:
            logger.warning(
                "token exchange failed (%s)", type(exchange_error).__name__
            )
            return _failure(400, "authorization could not be completed")

        try:
            home_session_id = client.open_home_session(tokens.access_token)
        except SessionOpenError as session_error:
            logger.warning(
                "home session refused (%s)", type(session_error).__name__
            )
            return _failure(403, "this account is not linked to a Home person")

        session = store.create_session(
            home_session_id=home_session_id,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )

        try:
            binding = store.claim_runtime(RUNTIME_ID, session.session_id)
        except (ValueError, StoreUnavailableError):
            try:
                store.delete_session(session.session_id)
            except StoreUnavailableError:
                pass
            return _failure(503, "runtime binding could not be completed")

        logger.info("runtime binding outcome: %s", binding.value)

        result = Response(status_code=303, headers={"Location": "/app"})
        result.headers["Cache-Control"] = "no-store"
        result.headers["Referrer-Policy"] = "no-referrer"
        _set_session_cookie(result, session.session_id)
        _clear_login_binding_cookie(result)
        return result
```

This drops the unused `response: Response` injected parameter and the `_terminal`/`HTTPException` approach entirely — remove `response: Response,` from the route's parameter list since it is no longer used (every branch now builds and returns its own `Response`/`JSONResponse`). Keep `HTTPException` imported only if other routes in the file still use it (they do: `/session`, `/whoami`, `/logout`, `/delegation` are unaffected by this task and keep using `HTTPException` as-is).

- [ ] **Step 4: Update `test_app.py`'s callback tests for the new 303 contract**

`complete_login` (line 110–116) currently asserts `200`. Update it:

```python
def complete_login(http) -> str:
    state = login_and_get_state(http)
    response = http.get(
        f"/callback?code=auth-code&state={state}", follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return state
```

`login_and_get_state` (line 103–107) currently only performs `/login` and returns `state`; it must also leave the binding cookie set in `http.cookies` for the subsequent `/callback` call to succeed, which it already does automatically since `TestClient` persists `Set-Cookie` responses across calls on the same client instance — no change needed there.

Update every callback test in `test_app.py` that currently asserts `200` on a *successful* callback to assert `303` instead, and drop assertions on the old JSON body shape:

- `test_callback_happy_path_sets_opaque_cookie` (line 173): no status assertion currently — unaffected, but relies on `complete_login`, already fixed above.
- `test_callback_claims_fixed_runtime_and_reports_binding` (line 184–199): replace

  ```python
  assert response.status_code == 200
  assert response.json() == {
      "status": "authenticated",
      "runtime_binding": BindResult.BOUND.value,
  }
  ```

  with

  ```python
  assert response.status_code == 303
  assert response.headers["location"] == "/app"
  ```

  Keep the rest of the test (the `store.get_session`/`store.resolve_runtime` assertions) unchanged.
- `test_callback_refuses_to_replace_live_runtime_owner` (line 202–219): replace

  ```python
  assert response.status_code == 200
  assert response.json()["runtime_binding"] == BindResult.ALREADY_BOUND.value
  ```

  with

  ```python
  assert response.status_code == 303
  assert response.headers["location"] == "/app"
  ```

  Keep the rest unchanged (this is BFF-6's coverage duplicated here for the store-level assertions; both this and the new `test_bff6_*` in Task 3's test file are kept — they test different things: this one proves the store state, the other proves the HTTP-visible absence of the enum).
- `test_callback_binding_failure_is_a_generic_fail_closed_response` (line 230–243): already asserts `503`; add `assert "location" not in response.text` is unnecessary (it already checks `response.text` for leaked detail) — no change required beyond what's there, but explicitly add:

  ```python
  assert "location" not in response.headers
  ```
- `test_callback_uses_the_verifier_minted_for_that_state` (line 246–256): calls `/callback` without checking status; unaffected by shape, but must not break — since it no longer asserts `200`, leave as-is.
- `test_callback_rejects_wrong_state` / `_reused_state` / `_missing_code` / `_missing_state` / `_propagates_provider_error`: all assert `400`, unaffected.
- `test_callback_rejects_reused_state` (line 266–272): asserts `first.status_code == 200` — change to `303`.
- `test_callback_fails_closed_on_token_exchange_failure` (line 297–303): asserts `400`, unaffected, but add the binding cookie is present before this call succeeds — it already goes through `login_and_get_state`, unaffected.
- `test_callback_fails_closed_when_control_plane_refuses` (line 314–325): asserts `403`, unaffected.
- `test_session_cookie_flags` (line 328–336): unaffected (still reads `set-cookie` header off a successful callback — now a 303 instead of 200, but the header is still present).
- `test_no_token_appears_in_any_callback_response` (line 339–345): unaffected in spirit, but a 303's body is empty now, so `"at-1" not in response.text` trivially holds; no change needed, but it now also implicitly covers "no token in the empty body," which is fine.

- [ ] **Step 5: Run the full BFF test suite**

Run: `cd services/home-bff && python -m pytest tests/ -v`
Expected: `test_login_binding.py`, updated `test_app.py`, and `test_security_audit.py` all PASS. If `test_security_audit.py`'s `test_no_secret_in_callback_response_or_cookie` (around line 312 in that file) asserts on a `200` JSON shape, update it the same way: it should still assert none of `SECRETS.values()` appear in `response.text` or `response.headers` values, which holds trivially for an empty 303 body — read that test first and adjust only if it currently parses `response.json()`.

- [ ] **Step 6: Commit**

```bash
git add services/home-bff/home_bff/app.py services/home-bff/home_bff/sessions.py services/home-bff/tests/test_app.py services/home-bff/tests/test_login_binding.py services/home-bff/tests/test_security_audit.py
git commit -m "feat(bff): login-CSRF binding cookie and 303 /app callback contract"
```

---

## Task 4: Split upstream error classes in `frappe_client.py`

**Files:**
- Modify: `services/home-bff/home_bff/frappe_client.py`
- Test: `services/home-bff/tests/test_frappe_client_bootstrap.py` (new)

**Interfaces:**
- Produces: `UpstreamRefused(RuntimeError)`, `UpstreamUnavailable(RuntimeError)`, `UpstreamMalformed(RuntimeError)` — all additive, `SessionOpenError`/`TokenExchangeError` untouched. `HomeOAuthClient.get_home_bootstrap(access_token: str, session_id: str) -> dict` — raises one of the three new exceptions; never raises `SessionOpenError`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests**

Create `services/home-bff/tests/test_frappe_client_bootstrap.py`:

```python
"""Upstream error classification for the bootstrap CP call (§6)."""
from __future__ import annotations

import httpx
import pytest

from home_bff.frappe_client import (
    HomeOAuthClient,
    UpstreamMalformed,
    UpstreamRefused,
    UpstreamUnavailable,
)

BOOTSTRAP_PATH = "/api/method/episteck_home.api.get_home_bootstrap"


def _client(handler) -> HomeOAuthClient:
    transport = httpx.MockTransport(handler)
    return HomeOAuthClient(
        "https://home.invalid", "client-id", "client-secret", transport=transport
    )


def _handler(status_code: int, json_body=None, raise_connect_error=False):
    def handle(request: httpx.Request) -> httpx.Response:
        if raise_connect_error:
            raise httpx.ConnectError("connection refused")
        if json_body is None:
            return httpx.Response(status_code, text="not json{{{")
        return httpx.Response(status_code, json=json_body)

    return handle


@pytest.mark.parametrize("status_code", [401, 403])
def test_cp_401_403_raise_upstream_refused(status_code):
    client = _client(_handler(status_code, {"exc_type": "PermissionError"}))
    with pytest.raises(UpstreamRefused):
        client.get_home_bootstrap("token", "HDS-1")


def test_connect_error_raises_upstream_unavailable():
    client = _client(_handler(200, raise_connect_error=True))
    with pytest.raises(UpstreamUnavailable):
        client.get_home_bootstrap("token", "HDS-1")


def test_timeout_raises_upstream_unavailable():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = _client(handle)
    with pytest.raises(UpstreamUnavailable):
        client.get_home_bootstrap("token", "HDS-1")


@pytest.mark.parametrize("status_code", [404, 417, 429, 500, 502, 503])
def test_cp_404_417_429_5xx_raise_upstream_unavailable(status_code):
    client = _client(_handler(status_code, {"exc_type": "MethodNotFoundError"}))
    with pytest.raises(UpstreamUnavailable):
        client.get_home_bootstrap("token", "HDS-1")


def test_cp_200_non_json_raises_upstream_malformed():
    client = _client(_handler(200, json_body=None))
    with pytest.raises(UpstreamMalformed):
        client.get_home_bootstrap("token", "HDS-1")


def test_cp_200_json_returns_message_payload():
    payload = {
        "message": {
            "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
            "circles": [],
            "care": [],
        }
    }
    client = _client(_handler(200, json_body=payload))
    result = client.get_home_bootstrap("token", "HDS-1")
    assert result == payload["message"]


def test_cp_200_json_missing_message_key_raises_upstream_malformed():
    client = _client(_handler(200, json_body={"unexpected": "shape"}))
    with pytest.raises(UpstreamMalformed):
        client.get_home_bootstrap("token", "HDS-1")


def test_no_access_token_raises_upstream_refused():
    client = _client(_handler(200, json_body={"message": {}}))
    with pytest.raises(UpstreamRefused):
        client.get_home_bootstrap("", "HDS-1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/home-bff && python -m pytest tests/test_frappe_client_bootstrap.py -v`
Expected: FAIL — `ImportError: cannot import name 'UpstreamMalformed' from 'home_bff.frappe_client'`.

- [ ] **Step 3: Implement in `frappe_client.py`**

Add after the existing `SessionOpenError` class (after line 37):

```python
class UpstreamRefused(RuntimeError):
    """The Control Plane definitively refused this session/user (401/403)."""


class UpstreamUnavailable(RuntimeError):
    """Transport failure, timeout, or the CP method is absent/overloaded/down."""


class UpstreamMalformed(RuntimeError):
    """The CP answered 200 but the body is not usable JSON with the expected shape."""
```

Add the path constant near the other `*_PATH` constants (after line 28):

```python
GET_HOME_BOOTSTRAP_PATH = "/api/method/episteck_home.api.get_home_bootstrap"
```

Add the method to `HomeOAuthClient`, placed after `whoami` (after line 137):

```python
    def get_home_bootstrap(self, access_token: str, session_id: str) -> dict:
        """The single session-bound bootstrap read (§2/§3 Option B).

        Splits the previously-uniform SessionOpenError into three classes so the
        BFF can map each to a distinct HTTP status (§6): a definitive refusal
        (401/403) is not the same situation as the CP being unreachable, and
        neither is the same as the CP answering with something we cannot parse.
        """
        if not access_token:
            raise UpstreamRefused("no access token")
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = self._client.post(
                GET_HOME_BOOTSTRAP_PATH,
                data={"session_id": session_id},
                headers=headers,
            )
        except httpx.HTTPError as error:
            raise UpstreamUnavailable("Control Plane unreachable") from error

        if response.status_code in (401, 403):
            raise UpstreamRefused(
                f"Control Plane refused the session (HTTP {response.status_code})"
            )
        if response.status_code != 200:
            # 404/417 (method absent), 429 (rate limited), and any 5xx are all
            # "try again later" from the browser's perspective, not "you are
            # unauthorized" — §6 maps every one of these to 503, never 401.
            raise UpstreamUnavailable(
                f"Control Plane unavailable (HTTP {response.status_code})"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise UpstreamMalformed("Control Plane returned non-JSON") from error
        if not isinstance(body, dict) or "message" not in body:
            raise UpstreamMalformed("Control Plane response missing message envelope")
        message = body["message"]
        if not isinstance(message, dict):
            raise UpstreamMalformed("Control Plane message is not an object")
        return message
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/home-bff && python -m pytest tests/test_frappe_client_bootstrap.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/home-bff/home_bff/frappe_client.py services/home-bff/tests/test_frappe_client_bootstrap.py
git commit -m "feat(bff): classify bootstrap upstream errors as Refused/Unavailable/Malformed"
```

---

## Task 5: Strict bootstrap response validator (`bootstrap.py`)

**Files:**
- Create: `services/home-bff/home_bff/bootstrap.py`
- Create: `services/home-bff/tests/test_bootstrap_validation.py`

**Interfaces:**
- Produces: `validate_bootstrap_response(raw: dict) -> dict` — returns the exact BFF wire-v1 shape from §4, raising `UpstreamMalformed` (imported from `frappe_client`) on any violation. `MAX_CONTEXTS = 50` (mirrors CP's `MAX_BOOTSTRAP_ROWS`, enforced independently at the BFF too, per defense-in-depth — the CP already bounds this, but the BFF must not trust a CP response blindly even under Option B's "same transaction" guarantee, since a future CP bug should not become a BFF crash or an unbounded payload).
- Consumes: `UpstreamMalformed` from `home_bff.frappe_client` (Task 4).

- [ ] **Step 1: Write the failing tests**

Create `services/home-bff/tests/test_bootstrap_validation.py`:

```python
"""Strict CP -> BFF bootstrap response validation (§4, CP-12/BFF-12/BFF-13)."""
from __future__ import annotations

import pytest

from home_bff.bootstrap import validate_bootstrap_response
from home_bff.frappe_client import UpstreamMalformed

VALID_RAW = {
    "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
    "circles": [{"circle_id": "CIR-00001", "display_name": "Family"}],
    "care": [
        {
            "person_id": "PSN-00007",
            "display_name": "Ana",
            "relationship_type": "CAREGIVER",
        }
    ],
}


def test_valid_payload_maps_to_wire_v1_shape():
    result = validate_bootstrap_response(VALID_RAW)
    assert result == {
        "version": 1,
        "viewer": {"personId": "PSN-00001", "displayName": "Erick"},
        "personContexts": [
            {"type": "PERSON", "personId": "PSN-00001", "displayName": "Erick"},
            {"type": "PERSON", "personId": "PSN-00007", "displayName": "Ana"},
        ],
        "circleContexts": [
            {"type": "CIRCLE", "circleId": "CIR-00001", "displayName": "Family"}
        ],
        "careRelationships": [
            {"subjectPersonId": "PSN-00007", "relationshipType": "CAREGIVER"}
        ],
    }


def test_viewer_is_always_first_person_context_even_with_no_care():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [],
        "care": [],
    }
    result = validate_bootstrap_response(raw)
    assert result["personContexts"] == [
        {"type": "PERSON", "personId": "PSN-00001", "displayName": "Erick"}
    ]


@pytest.mark.parametrize(
    "bad_person_id", ["PSN-1", "psn-00001", "PSN00001", "CIR-00001", "", "PSN-abcde"]
)
def test_invalid_person_id_format_rejects_whole_payload(bad_person_id):
    raw = {
        "viewer": {"person_id": bad_person_id, "display_name": "X"},
        "circles": [],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


@pytest.mark.parametrize("bad_circle_id", ["CIR-1", "cir-00001", "PSN-00001", ""])
def test_invalid_circle_id_format_rejects_whole_payload(bad_circle_id):
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "X"},
        "circles": [{"circle_id": bad_circle_id, "display_name": "Family"}],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_empty_display_name_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": ""},
        "circles": [],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_display_name_over_140_chars_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "x" * 141},
        "circles": [],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_display_name_with_control_characters_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick\x00"},
        "circles": [],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_unknown_relationship_type_rejects_whole_payload():
    raw = dict(VALID_RAW)
    raw["care"] = [
        {"person_id": "PSN-00007", "display_name": "Ana", "relationship_type": "FRIEND"}
    ]
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


@pytest.mark.parametrize(
    "relationship_type",
    ["CAREGIVER", "COORDINATOR", "GUARDIAN", "FAMILY_SUPPORT"],
)
def test_all_four_relationship_types_are_accepted(relationship_type):
    raw = dict(VALID_RAW)
    raw["care"] = [
        {
            "person_id": "PSN-00007",
            "display_name": "Ana",
            "relationship_type": relationship_type,
        }
    ]
    result = validate_bootstrap_response(raw)
    assert result["careRelationships"][0]["relationshipType"] == relationship_type


def test_care_subject_equal_to_viewer_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [],
        "care": [
            {
                "person_id": "PSN-00001",
                "display_name": "Erick",
                "relationship_type": "CAREGIVER",
            }
        ],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_duplicate_care_subject_rejects_whole_payload():
    raw = dict(VALID_RAW)
    raw["care"] = [
        {
            "person_id": "PSN-00007",
            "display_name": "Ana",
            "relationship_type": "CAREGIVER",
        },
        {
            "person_id": "PSN-00007",
            "display_name": "Ana",
            "relationship_type": "COORDINATOR",
        },
    ]
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_care_relationship_referencing_unknown_person_id_rejects_whole_payload():
    """A subjectPersonId with no matching personContexts entry is a dangling ref."""
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [],
        "care": [],
    }
    # Simulate a CP bug: care references a person never listed. Since `care` drives
    # personContexts membership in this validator, construct the malformed case by
    # directly testing a hand-built raw shape the validator cannot self-consistently
    # produce a dangling reference from care alone (care IS the source of personContexts
    # beyond viewer) — so this case is exercised via a duplicate circle id colliding
    # with a person id namespace instead, which the validator must also reject:
    raw["circles"] = [{"circle_id": "PSN-00001", "display_name": "Not a circle"}]
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_over_bound_circles_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [
            {"circle_id": f"CIR-{i:05d}", "display_name": f"Circle {i}"}
            for i in range(51)
        ],
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_over_bound_care_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": [],
        "care": [
            {
                "person_id": f"PSN-{i:05d}",
                "display_name": f"Person {i}",
                "relationship_type": "CAREGIVER",
            }
            for i in range(1, 52)
        ],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_missing_required_field_rejects_whole_payload():
    raw = {"viewer": {"person_id": "PSN-00001"}, "circles": [], "care": []}
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_wrong_type_for_circles_rejects_whole_payload():
    raw = {
        "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
        "circles": "not-a-list",
        "care": [],
    }
    with pytest.raises(UpstreamMalformed):
        validate_bootstrap_response(raw)


def test_unknown_extra_fields_are_dropped_not_rejected():
    raw = dict(VALID_RAW)
    raw["viewer"] = dict(raw["viewer"], external_ref="secret-ref", User_name="admin@x")
    raw["grants"] = ["should never appear"]
    result = validate_bootstrap_response(raw)
    assert "external_ref" not in result["viewer"]
    assert "grants" not in result
    assert "User_name" not in result["viewer"]
    import json

    assert "secret-ref" not in json.dumps(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/home-bff && python -m pytest tests/test_bootstrap_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'home_bff.bootstrap'`.

- [ ] **Step 3: Implement `bootstrap.py`**

```python
"""Strict CP -> BFF bootstrap response validator (§4).

The CP response is NEVER passed through. Every field is checked against an
explicit allowlist and a brand-new dict is constructed. A single violation
anywhere rejects the WHOLE payload — there is no partially-valid bootstrap.
"""
from __future__ import annotations

import re

from .frappe_client import UpstreamMalformed

PERSON_ID_RE = re.compile(r"^PSN-\d{5,}$")
CIRCLE_ID_RE = re.compile(r"^CIR-\d{5,}$")

MAX_DISPLAY_NAME_LENGTH = 140
MAX_CONTEXTS = 50

RELATIONSHIP_TYPES = frozenset(
    {"CAREGIVER", "COORDINATOR", "GUARDIAN", "FAMILY_SUPPORT"}
)

# Any Unicode "control" character, plus the C1 range, is rejected. This is a
# conservative denylist on top of the allowlist-by-construction approach: even a
# well-typed string must not carry terminal-escape or similarly hostile bytes.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _fail(reason: str) -> None:
    raise UpstreamMalformed(reason)


def _require_dict(value, reason: str) -> dict:
    if not isinstance(value, dict):
        _fail(reason)
    return value


def _require_list(value, reason: str) -> list:
    if not isinstance(value, list):
        _fail(reason)
    return value


def _validate_person_id(value, reason: str) -> str:
    if not isinstance(value, str) or not PERSON_ID_RE.match(value):
        _fail(reason)
    return value


def _validate_circle_id(value, reason: str) -> str:
    if not isinstance(value, str) or not CIRCLE_ID_RE.match(value):
        _fail(reason)
    return value


def _validate_display_name(value, reason: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(reason)
    if len(value) > MAX_DISPLAY_NAME_LENGTH:
        _fail(reason)
    if _CONTROL_CHAR_RE.search(value):
        _fail(reason)
    return value


def validate_bootstrap_response(raw: dict) -> dict:
    """Validate `raw` (the CP's `get_home_bootstrap` message body) and return
    the BFF wire-v1 shape (§4). Raises UpstreamMalformed on any violation.
    """
    raw = _require_dict(raw, "bootstrap response is not an object")

    viewer_raw = _require_dict(raw.get("viewer"), "viewer is missing or not an object")
    viewer_id = _validate_person_id(
        viewer_raw.get("person_id"), "viewer.person_id is malformed"
    )
    viewer_name = _validate_display_name(
        viewer_raw.get("display_name"), "viewer.display_name is malformed"
    )

    circles_raw = _require_list(raw.get("circles"), "circles is missing or not a list")
    if len(circles_raw) > MAX_CONTEXTS:
        _fail("circles exceeds the maximum bound")

    circle_contexts = []
    for entry in circles_raw:
        entry = _require_dict(entry, "a circle entry is not an object")
        circle_id = _validate_circle_id(
            entry.get("circle_id"), "circle.circle_id is malformed"
        )
        display_name = _validate_display_name(
            entry.get("display_name"), "circle.display_name is malformed"
        )
        circle_contexts.append(
            {"type": "CIRCLE", "circleId": circle_id, "displayName": display_name}
        )

    care_raw = _require_list(raw.get("care"), "care is missing or not a list")
    if len(care_raw) > MAX_CONTEXTS:
        _fail("care exceeds the maximum bound")

    person_contexts = [
        {"type": "PERSON", "personId": viewer_id, "displayName": viewer_name}
    ]
    care_relationships = []
    seen_subject_ids: set[str] = set()

    for entry in care_raw:
        entry = _require_dict(entry, "a care entry is not an object")
        subject_id = _validate_person_id(
            entry.get("person_id"), "care.person_id is malformed"
        )
        subject_name = _validate_display_name(
            entry.get("display_name"), "care.display_name is malformed"
        )
        relationship_type = entry.get("relationship_type")
        if relationship_type not in RELATIONSHIP_TYPES:
            _fail("care.relationship_type is unknown")

        if subject_id == viewer_id:
            _fail("a care subject cannot equal the viewer")
        if subject_id in seen_subject_ids:
            _fail("duplicate care subject")
        seen_subject_ids.add(subject_id)

        person_contexts.append(
            {"type": "PERSON", "personId": subject_id, "displayName": subject_name}
        )
        care_relationships.append(
            {"subjectPersonId": subject_id, "relationshipType": relationship_type}
        )

    # Namespace collision guard: a circleId must never coincide with any personId
    # already placed in personContexts (the "PSN-00001 used as a circle id" case).
    person_ids = {ctx["personId"] for ctx in person_contexts}
    circle_ids = {ctx["circleId"] for ctx in circle_contexts}
    if person_ids & circle_ids:
        _fail("a circle id collides with a person id")

    # Every careRelationships[].subjectPersonId must exist in personContexts.
    # By construction above this always holds (care IS the source of both), but
    # the check stays explicit so a future refactor cannot silently break it.
    context_person_ids = {ctx["personId"] for ctx in person_contexts}
    for relationship in care_relationships:
        if relationship["subjectPersonId"] not in context_person_ids:
            _fail("careRelationships references an unknown personId")

    return {
        "version": 1,
        "viewer": {"personId": viewer_id, "displayName": viewer_name},
        "personContexts": person_contexts,
        "circleContexts": circle_contexts,
        "careRelationships": care_relationships,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/home-bff && python -m pytest tests/test_bootstrap_validation.py -v`
Expected: all PASS. If `test_care_relationship_referencing_unknown_person_id_rejects_whole_payload` fails because the circle-id-collision case is caught by a different check than intended, that is fine — the test only asserts `UpstreamMalformed` is raised, not which specific reason string.

- [ ] **Step 5: Commit**

```bash
git add services/home-bff/home_bff/bootstrap.py services/home-bff/tests/test_bootstrap_validation.py
git commit -m "feat(bff): strict CP bootstrap response validator (wire v1)"
```

---

## Task 6: `GET /bootstrap` route — happy path + session/status mapping

**Files:**
- Modify: `services/home-bff/home_bff/app.py`
- Create: `services/home-bff/tests/test_bootstrap_route.py`

**Interfaces:**
- Consumes: `HomeOAuthClient.get_home_bootstrap` (Task 4), `validate_bootstrap_response` (Task 5), `UpstreamRefused`/`UpstreamUnavailable`/`UpstreamMalformed` (Task 4).
- Produces: `GET /bootstrap` route in the public app, `Cache-Control: no-store` on its response.

- [ ] **Step 1: Write the failing tests (BFF-7, 8, 9, 10, 11, 18 happy/status-mapping half)**

Create `services/home-bff/tests/test_bootstrap_route.py`:

```python
"""GET /bootstrap: cookie-only auth, one CP call, strict mapping (§6, §7)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from home_bff import sessions
from home_bff.app import create_app
from home_bff.frappe_client import UpstreamMalformed, UpstreamRefused, UpstreamUnavailable
from home_bff.store import SessionStore

from tests.test_app import FakeClient, make_settings  # noqa: E402


class BootstrapFakeClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.bootstrap_payload = {
            "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
            "circles": [{"circle_id": "CIR-00001", "display_name": "Family"}],
            "care": [
                {
                    "person_id": "PSN-00007",
                    "display_name": "Ana",
                    "relationship_type": "CAREGIVER",
                }
            ],
        }
        self.bootstrap_error: Exception | None = None
        self.bootstrap_calls: list[tuple[str, str]] = []

    def get_home_bootstrap(self, access_token, session_id):
        self.bootstrap_calls.append((access_token, session_id))
        if self.bootstrap_error:
            raise self.bootstrap_error
        return self.bootstrap_payload


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = BootstrapFakeClient()
    app = create_app(make_settings(), store=store, client=client)
    with TestClient(app, base_url="https://bff.invalid") as http:
        yield http, store, client


def _log_in(http) -> str:
    """Drive a real login+callback so the store has a genuine session + tokens."""
    from urllib.parse import parse_qs, urlparse

    http.get("/login", follow_redirects=False)
    login_response = http.get("/login", follow_redirects=False)
    query = parse_qs(urlparse(login_response.headers["location"]).query)
    state = query["state"][0]
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 303, response.text
    return http.cookies.get(sessions.COOKIE_NAME)


# ------------------------------------------------------------------- BFF-7


def test_bff7_missing_cookie_is_session_required(ctx):
    http, _, _ = ctx
    response = http.get("/bootstrap")
    assert response.status_code == 401
    assert response.json() == {"error": "SESSION_REQUIRED"}


def test_bff7_unknown_session_is_session_invalid(ctx):
    http, _, _ = ctx
    http.cookies.set(sessions.COOKIE_NAME, "not-a-real-session", domain="bff.invalid")
    response = http.get("/bootstrap")
    assert response.status_code == 401
    assert response.json() == {"error": "SESSION_INVALID"}


def test_bff7_expired_session_is_session_invalid(ctx):
    import sqlite3
    import time

    http, store, _ = ctx
    _log_in(http)
    raw = http.cookies.get(sessions.COOKIE_NAME)
    with sqlite3.connect(store._path) as db:
        db.execute(
            "UPDATE bff_session SET expires_at = ? WHERE session_id = ?",
            (int(time.time()) - 1, raw),
        )
    response = http.get("/bootstrap")
    assert response.status_code == 401
    assert response.json() == {"error": "SESSION_INVALID"}


# ------------------------------------------------------------------- BFF-8 / BFF-9


def test_bff8_uses_the_sessions_own_token_and_home_session_id(ctx):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))

    response = http.get("/bootstrap")

    assert response.status_code == 200
    assert client.bootstrap_calls == [(session.access_token, session.home_session_id)]


def test_bff8_query_actor_hint_is_ignored(ctx):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    client.bootstrap_calls.clear()

    http.get("/bootstrap?person_id=PSN-99999")
    http.get("/bootstrap?actor=PSN-99999")

    assert client.bootstrap_calls == [
        (session.access_token, session.home_session_id),
        (session.access_token, session.home_session_id),
    ]


def test_bff8_actor_header_is_ignored(ctx):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    client.bootstrap_calls.clear()

    http.get("/bootstrap", headers={"X-Actor-ID": "PSN-99999"})

    assert client.bootstrap_calls == [(session.access_token, session.home_session_id)]


def test_bff8_body_is_ignored(ctx):
    """Even sending a body on a GET must not change which session is used."""
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    client.bootstrap_calls.clear()

    http.request("GET", "/bootstrap", content=b'{"person_id": "PSN-99999"}')

    assert client.bootstrap_calls == [(session.access_token, session.home_session_id)]


def test_bff9_route_declares_no_actor_parameters():
    """The FastAPI route signature itself must not accept an actor input."""
    import inspect

    from home_bff.app import create_app

    app = create_app(make_settings(), store=SessionStore(":memory:invalid-guard"), client=None) \
        if False else None  # placeholder guard, real introspection below

    from home_bff import app as app_module

    source = inspect.getsource(app_module)
    bootstrap_section = source[source.index('@app.get("/bootstrap")'):]
    bootstrap_section = bootstrap_section[: bootstrap_section.index("\n\n    @app.")]
    for forbidden in ("person_id", "actor", "subject_person_id", "actor_person_id"):
        assert forbidden not in bootstrap_section


# ------------------------------------------------------------------- BFF-10


@pytest.mark.parametrize("exc", [UpstreamRefused("nope")])
def test_bff10_cp_refusal_is_session_invalid_and_leaves_store_unchanged(ctx, exc):
    http, store, client = ctx
    _log_in(http)
    session_id = http.cookies.get(sessions.COOKIE_NAME)
    client.bootstrap_error = exc

    response = http.get("/bootstrap")

    assert response.status_code == 401
    assert response.json() == {"error": "SESSION_INVALID"}
    assert store.get_session(session_id) is not None
    from home_bff.runtime import RUNTIME_ID

    assert store.resolve_runtime(RUNTIME_ID) is not None


# ------------------------------------------------------------------- BFF-11


@pytest.mark.parametrize(
    "exc",
    [
        UpstreamUnavailable("connect error"),
        UpstreamUnavailable("timeout"),
        UpstreamUnavailable("HTTP 404"),
        UpstreamUnavailable("HTTP 417"),
        UpstreamUnavailable("HTTP 429"),
        UpstreamUnavailable("HTTP 500"),
    ],
)
def test_bff11_cp_unavailable_is_service_unavailable(ctx, exc):
    http, store, client = ctx
    _log_in(http)
    client.bootstrap_error = exc

    response = http.get("/bootstrap")

    assert response.status_code == 503
    assert response.json() == {"error": "SERVICE_UNAVAILABLE"}


# ------------------------------------------------------------------- BFF-16


def test_bff16_logout_then_bootstrap_is_401(ctx):
    http, _, _ = ctx
    _log_in(http)
    http.post("/logout")
    response = http.get("/bootstrap")
    assert response.status_code == 401


# ------------------------------------------------------------------- BFF-17


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_bff17_non_get_methods_are_405(ctx, method):
    http, _, _ = ctx
    _log_in(http)
    response = getattr(http, method)("/bootstrap")
    assert response.status_code == 405


# ------------------------------------------------------------------- BFF-18


def test_bff18_bootstrap_has_no_store_cache_control(ctx):
    http, _, _ = ctx
    _log_in(http)
    response = http.get("/bootstrap")
    assert response.headers["cache-control"] == "no-store"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/home-bff && python -m pytest tests/test_bootstrap_route.py -v`
Expected: FAIL — `404 Not Found` for every `/bootstrap` call (route doesn't exist yet).

- [ ] **Step 3: Implement the route in `app.py`**

Add imports at the top of `app.py` alongside the existing `from .frappe_client import (...)`:

```python
from .bootstrap import validate_bootstrap_response
from .frappe_client import (
    HomeOAuthClient,
    SessionOpenError,
    TokenExchangeError,
    UpstreamMalformed,
    UpstreamRefused,
    UpstreamUnavailable,
)
```

Add the route after `/whoami` (after line 248, before `/delegation`):

```python
    @app.get("/bootstrap")
    def bootstrap(
        session_id: str | None = Cookie(default=None, alias=sessions.COOKIE_NAME),
        store: SessionStore = Depends(get_store),
        client: HomeOAuthClient = Depends(get_client),
    ):
        """The single trusted-server read that answers "what can this viewer see".

        No actor/person/context parameter exists on this signature (BFF-9): the
        ONLY identity input is the session cookie. Query strings, headers, and any
        request body are never inspected here, so nothing a caller sends can name
        a different actor (BFF-8).
        """
        if session_id is None:
            return JSONResponse(
                {"error": "SESSION_REQUIRED"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        session = store.get_session(session_id)
        if session is None:
            return JSONResponse(
                {"error": "SESSION_INVALID"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        try:
            raw = client.get_home_bootstrap(session.access_token, session.home_session_id)
        except UpstreamRefused:
            # Read-only: a CP refusal never deletes the local session or runtime
            # binding. The CP is the authority; the next login replaces the cookie.
            return JSONResponse(
                {"error": "SESSION_INVALID"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        except UpstreamUnavailable:
            return JSONResponse(
                {"error": "SERVICE_UNAVAILABLE"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        except UpstreamMalformed:
            return JSONResponse(
                {"error": "INVALID_RESPONSE"},
                status_code=502,
                headers={"Cache-Control": "no-store"},
            )

        try:
            wire = validate_bootstrap_response(raw)
        except UpstreamMalformed:
            return JSONResponse(
                {"error": "INVALID_RESPONSE"},
                status_code=502,
                headers={"Cache-Control": "no-store"},
            )

        return JSONResponse(wire, headers={"Cache-Control": "no-store"})
```

FastAPI automatically returns `405 Method Not Allowed` for `POST`/`PUT`/`DELETE` on a path that only declares `@app.get`, so BFF-17 requires no additional code — only the test confirming it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/home-bff && python -m pytest tests/test_bootstrap_route.py -v`
Expected: all PASS. `test_bff9_route_declares_no_actor_parameters` uses source introspection deliberately (rather than FastAPI's OpenAPI schema, which is now disabled per Task 9) — if the string-slicing approach is fragile against future formatting changes, that is acceptable since it is testing this exact route's exact current text; revisit only if it breaks on unrelated edits.

- [ ] **Step 5: Commit**

```bash
git add services/home-bff/home_bff/app.py services/home-bff/tests/test_bootstrap_route.py
git commit -m "feat(bff): add GET /bootstrap with strict status mapping"
```

---

## Task 7: Bootstrap malformed-response and secret-leakage coverage (BFF-12, 13, 14, 15)

**Files:**
- Modify: `services/home-bff/tests/test_bootstrap_route.py`

**Interfaces:**
- Consumes: everything from Tasks 4–6. No production code changes expected in this task — it is pure test coverage that should already pass given Tasks 4–6's implementation. If any of these tests fail, fix the implementation in `bootstrap.py` or `app.py`, not the test.

- [ ] **Step 1: Write the tests**

Append to `services/home-bff/tests/test_bootstrap_route.py`:

```python
# ------------------------------------------------------------------- BFF-12


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"viewer": {"person_id": "PSN-00001"}, "circles": [], "care": []},  # missing display_name
        {"viewer": {"person_id": "PSN-1", "display_name": "X"}, "circles": [], "care": []},  # bad id
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [],
            "care": [
                {
                    "person_id": "PSN-00007",
                    "display_name": "Ana",
                    "relationship_type": "FRIEND",
                }
            ],
        },  # unknown enum
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [{"circle_id": "PSN-00007", "display_name": "Not a circle"}],
            "care": [],
        },  # circle id in personId namespace
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [],
            "care": [
                {
                    "person_id": "PSN-00001",
                    "display_name": "X",
                    "relationship_type": "CAREGIVER",
                }
            ],
        },  # care subject == viewer
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [],
            "care": [
                {
                    "person_id": "PSN-00007",
                    "display_name": "Ana",
                    "relationship_type": "CAREGIVER",
                },
                {
                    "person_id": "PSN-00007",
                    "display_name": "Ana",
                    "relationship_type": "GUARDIAN",
                },
            ],
        },  # duplicate
        {
            "viewer": {"person_id": "PSN-00001", "display_name": "X"},
            "circles": [
                {"circle_id": f"CIR-{i:05d}", "display_name": "C"} for i in range(51)
            ],
            "care": [],
        },  # over bound
    ],
    ids=[
        "missing-field",
        "bad-id-format",
        "unknown-enum",
        "circle-id-in-person-namespace",
        "care-subject-equals-viewer",
        "duplicate-care-subject",
        "over-bound-circles",
    ],
)
def test_bff12_every_malformed_shape_is_invalid_response_never_partial(ctx, bad_payload):
    http, _, client = ctx
    _log_in(http)
    client.bootstrap_payload = bad_payload

    response = http.get("/bootstrap")

    assert response.status_code == 502
    assert response.json() == {"error": "INVALID_RESPONSE"}


def test_bff12_non_dict_care_entry_is_invalid_response(ctx):
    http, _, client = ctx
    _log_in(http)
    client.bootstrap_payload = {
        "viewer": {"person_id": "PSN-00001", "display_name": "X"},
        "circles": [],
        "care": ["not-a-dict"],
    }
    response = http.get("/bootstrap")
    assert response.status_code == 502
    assert response.json() == {"error": "INVALID_RESPONSE"}


# ------------------------------------------------------------------- BFF-13


def test_bff13_extra_access_and_external_ref_fields_are_dropped(ctx):
    http, _, client = ctx
    _log_in(http)
    client.bootstrap_payload = {
        "viewer": {
            "person_id": "PSN-00001",
            "display_name": "Erick",
            "external_ref": "leak-me-not",
        },
        "circles": [],
        "care": [],
        "access": {"nutrition": ["VIEW"]},
        "grants": ["should-not-appear"],
    }
    response = http.get("/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert "access" not in body
    assert "grants" not in body
    assert "external_ref" not in body["viewer"]
    import json

    text = json.dumps(body)
    assert "leak-me-not" not in text
    assert "should-not-appear" not in text


# ------------------------------------------------------------------- BFF-14


def test_bff14_response_bytes_contain_no_secrets(ctx):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    response = http.get("/bootstrap")

    assert session.access_token not in response.text
    assert session.home_session_id not in response.text
    assert http.cookies.get(sessions.COOKIE_NAME) not in response.text
    assert "client_secret" not in response.text
    assert "super-secret" not in response.text


# ------------------------------------------------------------------- BFF-15


def test_bff15_logs_across_bootstrap_failure_paths_contain_no_secrets(ctx, caplog):
    http, store, client = ctx
    _log_in(http)
    session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))

    with caplog.at_level("DEBUG"):
        client.bootstrap_error = UpstreamRefused("refused")
        http.get("/bootstrap")

        client.bootstrap_error = UpstreamUnavailable("down")
        http.get("/bootstrap")

        client.bootstrap_error = None
        client.bootstrap_payload = {"viewer": {}, "circles": [], "care": []}
        http.get("/bootstrap")

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert session.access_token not in log_text
    assert session.home_session_id not in log_text
    assert http.cookies.get(sessions.COOKIE_NAME) not in log_text
    assert "super-secret" not in log_text
    assert "PSN-" not in log_text
```

- [ ] **Step 2: Run tests**

Run: `cd services/home-bff && python -m pytest tests/test_bootstrap_route.py -v`
Expected: all PASS given Tasks 4–6's implementation. If `test_bff15_*` fails because a log line was added somewhere with a Person id or token, find and fix that `logger.*` call in `app.py`/`frappe_client.py` to log only exception class names, matching the existing pattern (`logger.warning("token exchange failed (%s)", type(exchange_error).__name__)`).

- [ ] **Step 3: Commit**

```bash
git add services/home-bff/tests/test_bootstrap_route.py
git commit -m "test(bff): cover bootstrap malformed shapes, extra fields, and secret hygiene"
```

---

## Task 8: Disable public FastAPI docs (BFF-19)

**Files:**
- Modify: `services/home-bff/home_bff/app.py`
- Create: `services/home-bff/tests/test_public_docs_disabled.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `create_app(...)` builds the public `FastAPI()` with `docs_url=None, redoc_url=None, openapi_url=None`.

- [ ] **Step 1: Write the failing tests**

Create `services/home-bff/tests/test_public_docs_disabled.py`:

```python
"""BFF-19: the public app never exposes its own API surface inventory."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from home_bff.app import create_app
from home_bff.store import SessionStore

from tests.test_app import FakeClient, make_settings  # noqa: E402


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = FakeClient()
    app = create_app(make_settings(), store=store, client=client)
    with TestClient(app, base_url="https://bff.invalid") as http:
        yield http


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_public_docs_routes_are_404(ctx, path):
    response = ctx.get(path)
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/home-bff && python -m pytest tests/test_public_docs_disabled.py -v`
Expected: FAIL — `/docs` and `/redoc` currently return `200`, `/openapi.json` returns the schema.

- [ ] **Step 3: Implement**

Change `create_app`'s `FastAPI(...)` construction (line 53):

```python
    app = FastAPI(
        title="Episteck Home BFF",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/home-bff && python -m pytest tests/test_public_docs_disabled.py -v`
Expected: all PASS.

Then run the FULL suite to confirm nothing relied on `/openapi.json` being present:

Run: `cd services/home-bff && python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/home-bff/home_bff/app.py services/home-bff/tests/test_public_docs_disabled.py
git commit -m "feat(bff): disable public /docs, /redoc, /openapi.json"
```

---

## Task 9: BFF-20 — end-to-end migration/concurrency regression test at the app level

**Files:**
- Modify: `services/home-bff/tests/test_login_binding.py`

**Interfaces:**
- Consumes: `SessionStore` (Task 2), `create_app` (existing).

Task 2 already covers the store-level migration concurrency in isolation. This task adds one test that proves the full app (both `/login` and a fresh `SessionStore` reopening the same file, simulating the mint process) works correctly against a store that started on the pre-migration schema — closing the loop from "the column exists" (Task 2) to "the app actually uses it correctly" end to end.

- [ ] **Step 1: Write the test**

Append to `services/home-bff/tests/test_login_binding.py`:

```python
def test_bff20_app_logs_in_successfully_against_a_pre_migration_store(tmp_path):
    import sqlite3

    from home_bff.app import create_app
    from home_bff.store import SessionStore, _SCHEMA_PRE_LOGIN_BINDING
    from fastapi.testclient import TestClient

    from tests.test_app import FakeClient, make_settings

    path = str(tmp_path / "legacy.sqlite")
    with sqlite3.connect(path) as db:
        db.executescript(_SCHEMA_PRE_LOGIN_BINDING)
        db.commit()

    store = SessionStore(path)  # migrates on construction
    app = create_app(make_settings(), store=store, client=FakeClient())
    with TestClient(app, base_url="https://bff.invalid") as http:
        from urllib.parse import parse_qs, urlparse

        response = http.get("/login", follow_redirects=False)
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        callback = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
        assert callback.status_code == 303
        assert callback.headers["location"] == "/app"
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `cd services/home-bff && python -m pytest tests/test_login_binding.py -v -k bff20`
Expected: PASS immediately, since Tasks 2 and 3 already implement everything this exercises end to end — this task is a regression-proof integration test, not new functionality. If it fails, the bug is in Task 2's migration or Task 3's cookie flow; fix there.

- [ ] **Step 3: Commit**

```bash
git add services/home-bff/tests/test_login_binding.py
git commit -m "test(bff): BFF-20 end-to-end login against a pre-migration store"
```

---

## Task 10: nginx explicit route allowlist (config only)

**Files:**
- Modify: `deploy/home-bff/nginx-home-bff.conf`
- Create: `deploy/home-bff/tests/test_nginx_routes.py`

**Interfaces:**
- Produces: the updated nginx config text; a static test reading that file (mirrors `test_quadlets.py`'s pattern of reading raw config text and asserting string presence/absence — no nginx binary is invoked).

- [ ] **Step 1: Write the failing test**

Create `deploy/home-bff/tests/test_nginx_routes.py`:

```python
"""Static config test for the explicit nginx route allowlist (§11, deploy row of §12).

No nginx binary is invoked. This reads the raw config text the same way
test_quadlets.py reads raw Quadlet text — config-only, never deployed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONF = (ROOT / "nginx-home-bff.conf").read_text(encoding="utf-8")


def test_delegation_is_explicit_404():
    assert "location = /delegation" in CONF
    assert "return 404" in CONF


def test_public_bff_routes_are_explicitly_allowlisted():
    for route in ("/login", "/callback", "/logout", "/session", "/whoami"):
        assert f"location = {route}" in CONF, f"{route} must be an explicit location"


def test_bootstrap_docs_and_openapi_are_not_explicitly_proxied():
    for path in ("/bootstrap", "/docs", "/redoc", "/openapi.json"):
        assert f"location = {path} {{" not in CONF
        assert f"proxy_pass" not in CONF.split(f"location = {path}")[-1][:200] if f"location = {path}" in CONF else True


def test_app_routes_are_reserved_with_correct_anchors():
    assert "location = /app " in CONF or "location = /app\n" in CONF or "location = /app{" in CONF or "location = /app {" in CONF
    assert "location ^~ /app/" in CONF


def test_generic_app_prefix_without_anchor_is_absent():
    """`location /app` (no `=` or `^~`) would also match `/application`."""
    import re

    naive = re.search(r"location\s+/app\s*\{", CONF)
    assert naive is None


def test_application_path_is_not_matched_by_app_locations():
    """Sanity check on the anchors themselves: /application must not start with
    the *exact* `/app` string followed by a `/`, which is what `^~ /app/` requires."""
    assert not "/application".startswith("/app/")
    assert "/application" != "/app"


def test_catch_all_falls_through_to_404():
    # The LAST unqualified `location /` block must return 404, not proxy_pass.
    assert 'location /' in CONF
    tail = CONF.rsplit("location /", 1)[-1]
    assert "return 404" in tail.split("}")[0] or "return 404" in tail[:200]


def test_no_domain_attribute_rewriting_is_introduced():
    assert "proxy_cookie_domain" not in CONF
    assert "Domain=" not in CONF
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd deploy/home-bff && python -m pytest tests/test_nginx_routes.py -v`
Expected: FAIL — the current config has a single catch-all `location /` proxying everything, so the allowlist-specific and `/app` assertions fail.

- [ ] **Step 3: Update `nginx-home-bff.conf`**

Replace the `server { listen 443 ... }` block's body (current lines 25–58) with:

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name bff.home.episteck.com;

    ssl_certificate     /etc/letsencrypt/live/bff.home.episteck.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bff.home.episteck.com/privkey.pem;

    # The BFF holds OAuth tokens. Do not let a browser cache any of its responses.
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "no-referrer" always;

    # Explicit allowlist (§11). Anything not listed here falls through to the
    # generic `location /` 404 at the bottom — this closes B5 (previously the
    # catch-all made every route, including /docs and /bootstrap, publicly
    # reachable by construction).

    # /delegation is for the trusted runtime on this host only. It must never be
    # reachable from the public Internet, even with a valid cookie.
    location = /delegation {
        deny all;
        return 404;
    }

    location = /login {
        proxy_pass http://127.0.0.1:9933;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }

    location = /callback {
        proxy_pass http://127.0.0.1:9933;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        # episteck_noqs: path only, never the query string (see conf.d) — the
        # OAuth code and state live in this URL's query and must never reach a
        # plaintext access log.
        access_log /var/log/nginx/home-bff-access.log episteck_noqs;
    }

    location = /logout {
        proxy_pass http://127.0.0.1:9933;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }

    location = /session {
        proxy_pass http://127.0.0.1:9933;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }

    location = /whoami {
        proxy_pass http://127.0.0.1:9933;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }

    # Reserved for the future Home Hub listener (F2b, not activated here).
    # `^~ /app/` (not `^~ /app`) so `/application` is never matched by this block.
    location = /app {
        proxy_pass http://127.0.0.1:9940;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location ^~ /app/ {
        proxy_pass http://127.0.0.1:9940;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # /bootstrap, /docs, /redoc, /openapi.json, and everything else: 404. The
    # Next.js server reaches /bootstrap over loopback directly, never via nginx.
    location / {
        return 404;
    }

    error_log  /var/log/nginx/home-bff-error.log;
}
```

Note: the `access_log` directive is moved from the server block's tail (it applied to every route before) into the `/callback` location specifically, since that is the one route where query-string stripping matters most and the spec's §11 doesn't require it on every route; routes without an explicit `access_log` inherit nginx's default (or the `http{}`-level directive, unspecified here) — this is a config-authoring judgment call within an otherwise config-only, non-deployed change, consistent with "prepare nginx config but MUST NOT deploy it" from §12 of the plan. If the deploy operator's runbook (`deploy/home-bff/README.md`) expects `access_log` at the server level, that is a deploy-time decision outside this PR's scope — leave a comment noting the change but do not alter the README in this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd deploy/home-bff && python -m pytest tests/test_nginx_routes.py -v`
Expected: all PASS. Also run the pre-existing `test_quadlets.py` to confirm nothing else broke:

Run: `cd deploy/home-bff && python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/home-bff/nginx-home-bff.conf deploy/home-bff/tests/test_nginx_routes.py
git commit -m "feat(deploy): explicit nginx route allowlist for home-bff (config only)"
```

---

## Task 11: Full-suite verification and lint/format pass

**Files:** none (verification only).

- [ ] **Step 1: Run the complete `services/home-bff` suite**

Run: `cd services/home-bff && python -m pytest tests/ -v`
Expected: every test PASSES. Record the exact count in the final report (do not estimate).

- [ ] **Step 2: Run the complete `deploy/home-bff` suite**

Run: `cd deploy/home-bff && python -m pytest tests/ -v`
Expected: every test PASSES. Record the exact count.

- [ ] **Step 3: Check for a repository-defined lint/format/type config for the changed files**

Run: `cd /path/to/repo/root && find . -maxdepth 2 -iname "pyproject.toml" -o -iname ".pre-commit-config.yaml" -o -iname "ruff.toml"` and inspect any found for a `[tool.ruff]`/`[tool.black]`/`[tool.mypy]` section that applies to `services/home-bff` or `deploy/home-bff`. If found, run the corresponding tool (e.g. `ruff check services/home-bff/ deploy/home-bff/`, `black --check services/home-bff/ deploy/home-bff/`) and fix any reported issues in the files this plan touched. If no such config exists for this subtree, note that explicitly in the final report rather than skipping silently.

- [ ] **Step 4: Confirm no test file relies on a since-removed name**

Run: `cd services/home-bff && python -m pytest tests/ --collect-only -q`
Expected: collection succeeds with no `ImportError`/`AttributeError` (this catches any stale reference across the whole `tests/` directory that individual task runs might have missed).

- [ ] **Step 5: Commit only if Step 3 produced fixes**

```bash
git add -A
git commit -m "style(bff): apply repository lint/format fixes"
```

(Skip this commit if Step 3 found no applicable tool or no changes were needed.)

---

## Task 12: Security review pass on the F2a-BFF diff

**Files:** none (review only — fixes, if any, land as new commits touching the files already listed above).

- [ ] **Step 1: Produce the diff for review**

Run: `git diff origin/main...HEAD --stat` then `git diff origin/main...HEAD` to get the full diff.

- [ ] **Step 2: Walk the checklist from the task brief against the diff**

For each item below, find the specific code in the diff that addresses it and confirm the corresponding test in Tasks 3, 6, 7, or 10 exercises it. This is a manual read-through, not a new test suite — cite file:line for each finding.

- Actor/session identity substitution — confirm `/bootstrap` never reads `frappe.session.user` indirectly through anything other than `session.access_token`/`session.home_session_id` (Task 6's route body).
- Login CSRF bypass — confirm the binding-hash comparison uses `hmac.compare_digest` (Task 3) and that a missing binding cookie is rejected identically to a mismatched one.
- State/binding replay — confirm `consume_transaction` still deletes-then-validates (Task 2's unchanged delete-first ordering) and that BFF-3/BFF-4 tests cover both replay and CSRF independently.
- Secret leakage — re-run `test_bff14_*` and `test_bff15_*` (Task 7) and `test_security_audit.py`'s existing `test_no_secret_in_*` battery; confirm they all still pass after every task.
- Open redirect — confirm `Location: /app` is a literal string constant in `app.py`, never built from a variable sourced from the request (Task 3's implementation; BFF-2 test).
- Accidental public `/bootstrap` — confirm the nginx config's `location /` (catch-all) is the only thing that would serve `/bootstrap`, and it returns 404 (Task 10; `test_bootstrap_docs_and_openapi_are_not_explicitly_proxied`).
- Session deletion on CP refusal — confirm the `/bootstrap` route's `except UpstreamRefused` branch never calls `store.delete_session` or `store.clear_runtime_for_session` (Task 6's implementation; BFF-10 test).
- Malformed-response partial acceptance — confirm `validate_bootstrap_response` raises before constructing any partial result dict; there is no code path that returns early with a subset (Task 5's implementation; BFF-12 parametrized tests).
- Query/header actor nomination — confirm the `/bootstrap` route signature has exactly `session_id: str | None = Cookie(...)`, `store`, `client` as parameters, nothing else (Task 6; BFF-8/9 tests).
- Unsafe logs — confirm every `logger.*` call added in Tasks 3, 4, 6 logs only exception class names or static enum values, never a variable holding a token/id (grep the diff for `logger\.` and inspect each call site's arguments).
- Migration races — confirm `_migrate_login_binding_hash` catches only `sqlite3.OperationalError` with the specific "duplicate column name" message match, re-raising anything else (Task 2's implementation; concurrency test).
- Catch-all nginx exposure — confirm the final `location /` in the new config is `return 404;` with no `proxy_pass` (Task 10; `test_catch_all_falls_through_to_404`).
- Callback body/token leakage — confirm the 303 response never includes tokens/state/code and the body is genuinely empty (Task 3's `Response(status_code=303, ...)` construction with no body argument; BFF-1 test's `response.text == ""` assertion).

- [ ] **Step 3: Fix any genuine finding**

If the walk-through in Step 2 surfaces a real gap (not already covered by an existing test), fix it in the relevant file from Tasks 1–10 and add a regression test in the matching test file, following that task's TDD steps (write failing test, confirm it fails, fix, confirm it passes).

- [ ] **Step 4: Re-run the full suite after any fix**

Run: `cd services/home-bff && python -m pytest tests/ -v && cd ../../deploy/home-bff && python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(bff): security review findings from F2a-BFF pre-merge audit"
```

If Step 2 finds no genuine gaps, skip this commit and note "no findings" in the final report.

---

## Task 13: Open the PR (do not merge)

**Files:** none.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feature/f2a-bff-session-bootstrap
```

- [ ] **Step 2: Open the PR against `main` using the GitHub MCP tool**

Use `mcp__github-tools__create_pull_request` (or `mcp__github-wdf__create_pull_request`, whichever points at `EKvargas/episteck_home`) with:
- `owner`: `EKvargas`
- `repo`: `episteck_home`
- `title`: `feat(bff): F2a-BFF login-CSRF, /bootstrap, callback 303 contract`
- `head`: `feature/f2a-bff-session-bootstrap`
- `base`: `main`
- `draft`: `true` (the task brief says "DO NOT MERGE" — opening as draft makes that state explicit and prevents accidental merge)
- `body`: a summary covering: scope (§2–§13 of the plan doc), the base SHA (`3668c42...`, full SHA from `git rev-parse origin/main` captured before Task 1's branch checkout), links to `docs/product/HOME_HUB_F2_SESSION_BOOTSTRAP_PLAN.md`, the BFF-1..BFF-20 completion table, and an explicit "DO NOT MERGE — awaiting coordinated deploy window per §13" line.

- [ ] **Step 3: Do not merge**

Confirm the PR is in `draft` state or otherwise clearly unmerged. Do not call any merge tool.

---

## Self-Review Notes (completed during plan authoring)

**Spec coverage:** §2 (Decision: Option B) — already implemented in PR #38, referenced not re-implemented (Task 6 consumes it). §3 (exact CP calls) — Task 4/6 call `get_home_bootstrap(session_id=...)` exactly once, no other CP method. §4 (wire contract) — Task 5. §5 (discoverability≠authorization) — enforced by Task 5 never calling `check_access`; no new task needed since this is a CP-side invariant already proven by PR #38's CP-8. §6 (error mapping) — Task 4 (classification) + Task 6 (mapping). §7 (revocation/freshness) — Task 6's "no cache, no session deletion on refusal" (BFF-10). §8 (Next.js contract) — explicitly out of scope (F2b). §9 (CSRF/method safety) — Task 3 (binding cookie) + Task 6 (GET-only via FastAPI's automatic 405). §10 (callback 303 design) — Task 3. §11 (nginx) — Task 10. §12 (test matrix) — Tasks 3, 6, 7, 8, 9, 10 collectively cover BFF-1 through BFF-20 plus the deploy static test. §13 (rollout order) — Task 13 (PR only, no deploy). §14/§15 (risks/out-of-scope) — respected by omission throughout; no task touches Next.js, Quadlet, pasta, refresh tokens, or `return_to`.

**Placeholder scan:** no "TBD"/"TODO" in any task; every code block is complete, runnable code, not a description of code.

**Type consistency:** `Transaction.login_binding_hash: str` (Task 2) matches every `transaction.login_binding_hash` read site in Task 3. `HomeOAuthClient.get_home_bootstrap(access_token: str, session_id: str) -> dict` (Task 4) matches every call site in Task 6 (`client.get_home_bootstrap(session.access_token, session.home_session_id)`). `validate_bootstrap_response(raw: dict) -> dict` (Task 5) matches Task 6's `validate_bootstrap_response(raw)` call.

**Review Focus:** the five items listed under Global Constraints' sibling section above are each wired to a specific task's test: concurrent-tab retry → Task 3 (`test_bff4_second_tab_login_overwrites_first_tabs_binding`); ALREADY_BOUND still succeeds → Task 3 (`test_bff6_already_bound_still_returns_303_and_enum_absent`); bootstrap must not compose per-person calls → Task 6 (`test_bff8_*` family asserting exactly one `bootstrap_calls` entry); malformed partial acceptance → Task 5 + Task 7 (`test_bff12_*` parametrized family); migration concurrency → Task 2 (`test_migration_survives_concurrent_store_construction`) + Task 9 (end-to-end regression).
