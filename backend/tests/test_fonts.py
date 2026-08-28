import sys
from importlib import resources
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from slidecaptain.fonts import installer


# ---- 동봉 자산 실재와 유효성 ----------------------------------------------


def test_bundled_font_files_exist_and_are_noto_sans_kr():
    paths = installer._bundled_font_paths()
    assert {p.name for p in paths} == {"NotoSansKR-Regular.ttf", "NotoSansKR-Bold.ttf"}
    for path in paths:
        assert path.exists()
        font = TTFont(str(path))
        assert font["name"].getDebugName(1) == "Noto Sans KR"


def test_bundled_license_file_exists():
    ref = resources.files("slidecaptain.fonts").joinpath("assets", "OFL.txt")
    assert ref.is_file()
    assert "SIL OPEN FONT LICENSE" in ref.read_text("utf-8").upper()


# ---- _user_font_dir 플랫폼 분기 -------------------------------------------


def test_user_font_dir_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "C:/fake/localappdata")
    assert installer._user_font_dir() == Path("C:/fake/localappdata") / "Microsoft/Windows/Fonts"


def test_user_font_dir_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert installer._user_font_dir() == Path.home() / "Library/Fonts"


def test_user_font_dir_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert installer._user_font_dir() == Path.home() / ".local/share/fonts"


# ---- font_installed --------------------------------------------------------


def test_font_installed_true_when_user_dir_has_font(tmp_path, monkeypatch):
    user_dir = tmp_path / "user_fonts"
    user_dir.mkdir()
    (user_dir / "NotoSansKR-Regular.ttf").write_bytes(b"fake")
    monkeypatch.setattr(installer, "_user_font_dir", lambda: user_dir)
    monkeypatch.setattr(installer, "_system_font_dirs", lambda: [])
    assert installer.font_installed() is True


def test_font_installed_true_when_system_dir_has_font(tmp_path, monkeypatch):
    system_dir = tmp_path / "system_fonts"
    system_dir.mkdir()
    (system_dir / "NotoSansKR-Bold.ttf").write_bytes(b"fake")
    monkeypatch.setattr(installer, "_user_font_dir", lambda: tmp_path / "user_fonts_absent")
    monkeypatch.setattr(installer, "_system_font_dirs", lambda: [system_dir])
    assert installer.font_installed() is True


def test_font_installed_false_when_neither_has_font(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "_user_font_dir", lambda: tmp_path / "user_fonts_absent")
    monkeypatch.setattr(installer, "_system_font_dirs", lambda: [])
    assert installer.font_installed() is False


# ---- install_fonts ----------------------------------------------------------


def test_install_fonts_copies_bundled_ttfs(tmp_path, monkeypatch):
    fake_user_dir = tmp_path / "user_fonts"
    monkeypatch.setattr(installer, "_user_font_dir", lambda: fake_user_dir)
    monkeypatch.setattr(sys, "platform", "linux")  # winreg 분기 회피

    result = installer.install_fonts()

    assert fake_user_dir.exists()
    assert {p.name for p in result} == {"NotoSansKR-Regular.ttf", "NotoSansKR-Bold.ttf"}
    for path in result:
        assert path.exists()
        assert path.stat().st_size > 0


def test_install_fonts_registers_windows_registry(tmp_path, monkeypatch):
    fake_user_dir = tmp_path / "user_fonts"
    monkeypatch.setattr(installer, "_user_font_dir", lambda: fake_user_dir)
    monkeypatch.setattr(sys, "platform", "win32")

    recorded: dict = {}

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeWinreg:
        HKEY_CURRENT_USER = object()
        KEY_SET_VALUE = object()
        REG_SZ = object()

        @staticmethod
        def OpenKey(hive, subkey, reserved, access):
            recorded["opened_key"] = subkey
            return FakeKey()

        @staticmethod
        def SetValueEx(key, value_name, reserved, value_type, data):
            recorded.setdefault("values", {})[value_name] = data

    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg())

    installer.install_fonts()

    assert recorded["opened_key"] == installer._REG_KEY
    assert set(recorded["values"]) == {
        "Noto Sans KR (TrueType)",
        "Noto Sans KR Bold (TrueType)",
    }
    for path_str in recorded["values"].values():
        assert path_str.endswith(".ttf")
        assert Path(path_str).is_absolute()


# ---- ensure_fonts -----------------------------------------------------------


def test_ensure_fonts_already_when_font_present(tmp_path, monkeypatch):
    user_dir = tmp_path / "user_fonts"
    user_dir.mkdir()
    (user_dir / "NotoSansKR-Regular.ttf").write_bytes(b"fake")
    monkeypatch.setattr(installer, "_user_font_dir", lambda: user_dir)
    monkeypatch.setattr(installer, "_system_font_dirs", lambda: [])

    assert installer.ensure_fonts() == "already"


def test_ensure_fonts_installs_when_absent(tmp_path, monkeypatch):
    user_dir = tmp_path / "user_fonts"
    monkeypatch.setattr(installer, "_user_font_dir", lambda: user_dir)
    monkeypatch.setattr(installer, "_system_font_dirs", lambda: [])
    monkeypatch.setattr(sys, "platform", "linux")

    assert installer.ensure_fonts() == "installed"
    assert (user_dir / "NotoSansKR-Regular.ttf").exists()
    assert (user_dir / "NotoSansKR-Bold.ttf").exists()
