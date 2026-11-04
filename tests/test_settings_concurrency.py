"""Concurrent partial updates must preserve unrelated branding and settings."""
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hub import core


@pytest.fixture
def installation():
    root = Path(__file__).resolve().parents[2] / ".settings-concurrency-tests" / uuid.uuid4().hex
    app = core.create_app(root / "data", {
        "TESTING": True, "REGISTER_EXTENSIONS": False, "CSRF_ENABLED": False,
        "LEGACY_DATA_DIR": root / "unused",
    })
    client = app.test_client()
    assert client.post("/setup", json={"username": "owner", "password": "synthetic-test-password"}).status_code == 200
    return app


def post_as_owner(app, endpoint, payload):
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "owner"
    response = client.post(endpoint, json=payload)
    return response.status_code, response.get_json()


@pytest.mark.parametrize("first_kind", ["settings", "branding"])
def test_concurrent_partial_updates_preserve_branding(installation, monkeypatch, first_kind):
    app = installation
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
    if first_kind == "settings":
        original = core.configure

        def pause(*args):
            entered.set()
            assert release.wait(5), "First request was not released"
            return original(*args)

        monkeypatch.setattr(core, "configure", pause)
        first_endpoint, first_payload = "/api/settings", {"hevc_support": True, "resources": {"profile": "minimal"}}
    else:
        original = core.text

        def pause(value, *args, **kwargs):
            if value == "Concurrent name":
                entered.set()
                assert release.wait(5), "First request was not released"
            return original(value, *args, **kwargs)

        monkeypatch.setattr(core, "text", pause)
        first_endpoint, first_payload = "/api/branding", {"name": "Concurrent name"}

    def second():
        second_started.set()
        return post_as_owner(app, "/api/branding", {"accent": "#236789", "logo_icon": "layers"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post_as_owner, app, first_endpoint, first_payload)
        assert entered.wait(5), "First request did not reach the read/merge stage"
        other = pool.submit(second)
        assert second_started.wait(5)
        # The second request must not commit while the first holds a snapshot.
        try:
            with pytest.raises(TimeoutError):
                other.result(timeout=.15)
        finally:
            release.set()
        assert first.result(timeout=5)[0] == 200
        assert other.result(timeout=5)[0] == 200

    saved = app.extensions["vwshub"].settings()
    assert saved["branding"]["accent"] == "#236789"
    assert saved["branding"]["logo_icon"] == "layers"
    if first_kind == "settings":
        assert saved["hevc_support"] is True
        assert saved["resources"]["profile"] == "minimal"
    else:
        assert saved["branding"]["name"] == "Concurrent name"
