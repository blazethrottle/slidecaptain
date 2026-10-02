"""Release bootstrap regressions without downloads or starting user servers."""

import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest


def _script(name):
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = _script("release_launcher")
builder = _script("build_release")


def _bundle(tmp_path):
    (tmp_path / "app.whl").write_bytes(b"wheel")
    (tmp_path / "requirements.txt").write_text("fastapi==0.141.0\n", encoding="utf-8")
    manifest = {"product": "SlideCaptain", "version": "0.2.0", "wheel": "app.whl",
                "wheel_sha256": launcher.sha256(tmp_path / "app.whl"), "requirements": "requirements.txt",
                "requirements_sha256": launcher.sha256(tmp_path / "requirements.txt")}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


@pytest.mark.parametrize("filename", ["app.whl", "requirements.txt"])
def test_corrupt_release_stops_before_install(tmp_path, monkeypatch, filename):
    _bundle(tmp_path)
    (tmp_path / filename).write_text("tampered", encoding="utf-8")
    install = Mock()
    monkeypatch.setattr(launcher, "ensure_environment", install)
    with pytest.raises(ValueError, match="검증 실패"):
        launcher.run_release(tmp_path, install_only=True)
    install.assert_not_called()


def test_manifest_cannot_escape_bundle(tmp_path):
    manifest = _bundle(tmp_path)
    manifest["wheel"] = "../app.whl"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="경로"):
        launcher.load_manifest(tmp_path)


def test_installed_release_skips_dependency_downloads(tmp_path, monkeypatch):
    manifest = _bundle(tmp_path)
    python = launcher.venv_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    marker = tmp_path / ".venv" / "slidecaptain-release.json"
    marker.write_text(json.dumps({key: manifest[key] for key in
                                 ("version", "wheel_sha256", "requirements_sha256")}), encoding="utf-8")
    run = Mock()
    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.ensure_environment(tmp_path, manifest) == python
    run.assert_not_called()


def test_failed_install_does_not_mark_complete(tmp_path, monkeypatch):
    manifest = _bundle(tmp_path)
    monkeypatch.setattr(launcher.venv, "EnvBuilder", lambda **kwargs: Mock(create=Mock()))
    monkeypatch.setattr(launcher.subprocess, "run", Mock(side_effect=subprocess.CalledProcessError(1, "pip")))
    with pytest.raises(subprocess.CalledProcessError):
        launcher.ensure_environment(tmp_path, manifest)
    assert not (tmp_path / ".venv" / "slidecaptain-release.json").exists()


@pytest.mark.parametrize("platform,symlinks", [("darwin", True), ("linux", True), ("win32", False)])
def test_bootstrap_links_managed_python_on_posix(tmp_path, monkeypatch, platform, symlinks):
    manifest = _bundle(tmp_path)
    monkeypatch.setattr(launcher.sys, "platform", platform)
    create = Mock()
    environment = Mock(return_value=Mock(create=create))
    monkeypatch.setattr(launcher.venv, "EnvBuilder", environment)
    monkeypatch.setattr(launcher.subprocess, "run", Mock())
    # The mock environment still needs its directory for the completion marker.
    (tmp_path / ".venv").mkdir()
    launcher.ensure_environment(tmp_path, manifest)
    environment.assert_called_once_with(with_pip=True, symlinks=symlinks)
    create.assert_called_once_with(tmp_path / ".venv")


def test_existing_matching_server_only_opens_browser(tmp_path, monkeypatch):
    _bundle(tmp_path)
    monkeypatch.setattr(launcher, "port_in_use", lambda port: True)
    monkeypatch.setattr(launcher, "read_health", lambda port: {"product": "slidecaptain", "version": "0.2.0", "ui_ready": True})
    browser, install, start = Mock(), Mock(), Mock()
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    monkeypatch.setattr(launcher, "ensure_environment", install)
    monkeypatch.setattr(launcher.subprocess, "Popen", start)
    assert launcher.run_release(tmp_path) == 0
    browser.assert_called_once_with("http://127.0.0.1:8765")
    install.assert_not_called()
    start.assert_not_called()


@pytest.mark.parametrize("health", [None, {"product": "other", "version": "0.2.0", "ui_ready": True},
                                    {"product": "slidecaptain", "version": "0.1.0", "ui_ready": True},
                                    {"product": "slidecaptain", "version": "0.2.0", "ui_ready": False}])
def test_foreign_or_old_server_is_not_modified(tmp_path, monkeypatch, health):
    _bundle(tmp_path)
    monkeypatch.setattr(launcher, "port_in_use", lambda port: True)
    monkeypatch.setattr(launcher, "read_health", lambda port: health)
    start = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", start)
    with pytest.raises(ValueError, match="Ctrl"):
        launcher.run_release(tmp_path)
    start.assert_not_called()


def test_keyboard_interrupt_stops_only_owned_child(tmp_path, monkeypatch):
    _bundle(tmp_path)
    monkeypatch.setattr(launcher, "port_in_use", lambda port: False)
    monkeypatch.setattr(launcher, "ensure_environment", lambda folder, manifest: Path("python"))
    monkeypatch.setattr(launcher, "read_health", lambda port: {"product": "slidecaptain", "version": "0.2.0", "ui_ready": True})
    child = Mock()
    child.poll.return_value = None
    child.wait.side_effect = [KeyboardInterrupt(), 0]
    start = Mock(return_value=child)
    monkeypatch.setattr(launcher.subprocess, "Popen", start)
    browser = Mock()
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    with pytest.raises(KeyboardInterrupt):
        launcher.run_release(tmp_path, no_browser=True, port=8872, data_dir=tmp_path / "projects")
    child.terminate.assert_called_once()
    browser.assert_not_called()
    assert start.call_args.args[0][-4:] == ["--port", "8872", "--data-dir", str(tmp_path / "projects")]


def test_stage_excludes_untracked_private_files(tmp_path):
    root, stage = tmp_path / "repo", tmp_path / "stage"
    package = root / "backend" / "slidecaptain"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '0.2.0'\n", encoding="utf-8")
    (root / "backend" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (package / "private.json").write_text("secret", encoding="utf-8")
    ui = root / "frontend" / "dist"
    ui.mkdir(parents=True)
    (ui / "index.html").write_text("ui", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "backend/slidecaptain/__init__.py", "backend/pyproject.toml"], check=True)
    stage.mkdir()
    builder.stage_backend(root, stage)
    assert (stage / "slidecaptain" / "__init__.py").exists()
    assert not (stage / "slidecaptain" / "private.json").exists()
    assert (stage / "slidecaptain" / "ui" / "index.html").read_text() == "ui"


def test_archive_preserves_executable_launcher_and_refuses_overwrite(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "Start-SlideCaptain.command").write_text(builder.MAC_LAUNCHER, encoding="ascii")
    destination = tmp_path / "release.zip"
    builder.write_zip(bundle, destination)
    original = destination.read_bytes()
    with zipfile.ZipFile(destination) as archive:
        assert (archive.getinfo("Start-SlideCaptain.command").external_attr >> 16) & 0o111 == 0o111
    with pytest.raises(FileExistsError):
        builder.write_zip(bundle, destination)
    assert destination.read_bytes() == original
