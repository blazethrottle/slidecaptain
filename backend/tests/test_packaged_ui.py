"""The CLI serves UI assets from an installed package or a source checkout."""

from fastapi.testclient import TestClient

from slidecaptain import __main__ as cli


def _layout(tmp_path, monkeypatch):
    package = tmp_path / "backend" / "slidecaptain"
    package.mkdir(parents=True)
    monkeypatch.setattr(cli, "__file__", str(package / "__main__.py"))
    return package / "ui", tmp_path / "frontend" / "dist"


def _write_ui(directory, label):
    directory.mkdir(parents=True)
    (directory / "index.html").write_text(f"<html>{label}</html>", encoding="utf-8")
    assets = directory / "assets"
    assets.mkdir()
    (assets / "app.js").write_text(f"console.log('{label}')", encoding="utf-8")


def test_installed_package_serves_bundled_ui_and_assets(tmp_path, monkeypatch):
    packaged, source = _layout(tmp_path, monkeypatch)
    _write_ui(packaged, "packaged")
    _write_ui(source, "source")
    with TestClient(cli._build_serve_app(tmp_path / "data", None)) as client:
        assert client.get("/").text == "<html>packaged</html>"
        assert client.get("/assets/app.js").text == "console.log('packaged')"
        assert client.get("/openapi.json").status_code == 200


def test_source_checkout_serves_built_frontend(tmp_path, monkeypatch):
    packaged, source = _layout(tmp_path, monkeypatch)
    # An incomplete packaging directory must not hide a valid source build.
    packaged.mkdir()
    _write_ui(source, "source")
    with TestClient(cli._build_serve_app(tmp_path / "data", None)) as client:
        assert client.get("/").text == "<html>source</html>"
        assert client.get("/assets/app.js").status_code == 200


def test_without_ui_api_still_runs(tmp_path, monkeypatch, capsys):
    _layout(tmp_path, monkeypatch)
    monkeypatch.setattr("slidecaptain.fonts.installer.ensure_fonts", lambda: "already-installed")
    apps = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: apps.append(app))
    assert cli.main(["serve", "--data-dir", str(tmp_path / "data")]) == 0
    assert "API만 제공합니다" in capsys.readouterr().out
    with TestClient(apps[0]) as client:
        assert client.get("/").status_code == 404
        assert client.get("/openapi.json").status_code == 200


def test_packaged_serve_does_not_report_missing_ui(tmp_path, monkeypatch, capsys):
    packaged, _ = _layout(tmp_path, monkeypatch)
    _write_ui(packaged, "packaged")
    monkeypatch.setattr("slidecaptain.fonts.installer.ensure_fonts", lambda: "already-installed")
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: None)
    assert cli.main(["serve", "--data-dir", str(tmp_path / "data")]) == 0
    assert "API만 제공합니다" not in capsys.readouterr().out
