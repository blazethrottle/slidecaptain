"""Launchers can identify the local app without checking AI credentials."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from slidecaptain import __version__
from slidecaptain.server.app import create_app


@pytest.mark.parametrize("ui_kind", ["none", "empty", "directory", "ready"])
def test_health_reports_product_version_and_actual_ui_file(store, tmp_path, ui_kind):
    static_dir = None
    if ui_kind != "none":
        static_dir = tmp_path / "ui"
        static_dir.mkdir()
        if ui_kind == "directory":
            (static_dir / "index.html").mkdir()
        elif ui_kind == "ready":
            (static_dir / "index.html").write_text("<!doctype html><title>SlideCaptain</title>")
    checker = Mock(side_effect=AssertionError("Health must not check AI login"))
    connections = Mock()
    connections.selected_status.side_effect = AssertionError("Health must not check AI connections")
    with TestClient(create_app(store, static_dir=static_dir, login_checker=checker,
                               ai_connections=connections)) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "product": "slidecaptain", "version": __version__, "ui_ready": ui_kind == "ready",
    }
    checker.assert_not_called()
    connections.selected_status.assert_not_called()
    connections.settings.assert_not_called()
    connections.provider.assert_not_called()


def test_health_rechecks_ui_readiness_when_files_change(store, tmp_path):
    static_dir = tmp_path / "ui"
    static_dir.mkdir()
    with TestClient(create_app(store, static_dir=static_dir)) as client:
        assert client.get("/api/health").json()["ui_ready"] is False
        (static_dir / "index.html").write_text("<!doctype html>")
        assert client.get("/api/health").json()["ui_ready"] is True
        (static_dir / "index.html").unlink()
        assert client.get("/api/health").json()["ui_ready"] is False
