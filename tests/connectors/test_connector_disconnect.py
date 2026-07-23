"""Disconnecting a connector must stick — issue: Apple Notes/iMessage/HN.

These connectors' is_connected() reports availability (file on disk, always-on
feed), never the _connected flag their disconnect() sets, so the UI button was
a no-op. Status now routes through the router's persisted opt-out set.
"""

import json

import pytest

from openjarvis.server import connectors_router


@pytest.fixture
def opt_out_file(tmp_path, monkeypatch):
    path = tmp_path / "disconnected.json"
    monkeypatch.setattr(connectors_router, "_OPT_OUT_PATH", path)
    # GET /connectors instantiates every connector into the module-level
    # cache, picking up whatever real credentials sit in ~/.openjarvis.
    # Leaving those behind makes later tests see a connected gcalendar and
    # fail. Give this module its own cache and restore the shared one after.
    monkeypatch.setattr(connectors_router, "_instances", {})
    return path


def test_opt_out_round_trip(opt_out_file):
    assert connectors_router._opt_outs() == set()

    connectors_router._set_opt_out("apple_notes", True)
    connectors_router._set_opt_out("imessage", True)
    assert connectors_router._opt_outs() == {"apple_notes", "imessage"}

    # Survives a restart: state lives on disk, not in the instance cache.
    assert set(json.loads(opt_out_file.read_text())) == {"apple_notes", "imessage"}

    connectors_router._set_opt_out("apple_notes", False)
    assert connectors_router._opt_outs() == {"imessage"}


def test_disconnect_sticks_through_the_api(opt_out_file):
    """POST /disconnect then GET / must not show the connector as connected."""
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = fastapi.FastAPI()
    app.include_router(connectors_router.create_connectors_router())
    client = TestClient(app)

    def status_of(cid):
        body = client.get("/v1/connectors").json()
        return next(
            c["connected"] for c in body["connectors"] if c["connector_id"] == cid
        )

    # HackerNews hardcodes is_connected() -> True, the worst case for this bug.
    assert status_of("hackernews") is True

    assert client.post("/v1/connectors/hackernews/disconnect").status_code == 200
    assert status_of("hackernews") is False  # regressed to True before the fix

    # Sibling connectors are untouched by one connector's opt-out.
    assert "hackernews" in connectors_router._opt_outs()
    assert "apple_notes" not in connectors_router._opt_outs()


def test_unwritable_opt_out_path_does_not_raise(tmp_path, monkeypatch):
    # A read-only home shouldn't 500 the disconnect endpoint.
    monkeypatch.setattr(
        connectors_router, "_OPT_OUT_PATH", tmp_path / "nope" / "x.json"
    )
    monkeypatch.setattr(
        connectors_router.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError)
    )
    connectors_router._set_opt_out("apple_notes", True)  # must not raise
