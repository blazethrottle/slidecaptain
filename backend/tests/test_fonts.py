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
    # 이 테스트는 레지스트리 기록만 본다. 즉시 반영 호출은 별도 테스트에서 검증한다.
    monkeypatch.setattr(installer, "_refresh_windows_fonts", lambda paths: None)

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
        def CreateKeyEx(hive, subkey, reserved, access):
            # 키가 없는 계정도 실패 없이 만들어지는 것을 흉내낸다 (OpenKey와 달리
            # FileNotFoundError를 내지 않음)
            recorded["created_key"] = subkey
            return FakeKey()

        @staticmethod
        def SetValueEx(key, value_name, reserved, value_type, data):
            recorded.setdefault("values", {})[value_name] = data

    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg())

    installer.install_fonts()

    assert recorded["created_key"] == installer._REG_KEY
    assert set(recorded["values"]) == {
        "Noto Sans KR (TrueType)",
        "Noto Sans KR Bold (TrueType)",
    }
    for path_str in recorded["values"].values():
        assert path_str.endswith(".ttf")
        assert Path(path_str).is_absolute()


def _fake_winreg_module():
    """레지스트리 기록만 성공시키는 최소 가짜 winreg (즉시 반영 테스트가 재사용)."""

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
        def CreateKeyEx(hive, subkey, reserved, access):
            return FakeKey()

        @staticmethod
        def SetValueEx(key, value_name, reserved, value_type, data):
            pass

    return FakeWinreg()


def test_install_fonts_refreshes_windows_fonts_immediately(tmp_path, monkeypatch):
    fake_user_dir = tmp_path / "user_fonts"
    monkeypatch.setattr(installer, "_user_font_dir", lambda: fake_user_dir)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg_module())

    calls: dict = {"add_font": [], "broadcast": []}

    class FakeGdi32:
        def AddFontResourceW(self, path):
            calls["add_font"].append(path)
            return 1

    class FakeUser32:
        def SendMessageTimeoutW(self, *args):
            calls["broadcast"].append(args)
            return 1

    class FakeWindll:
        def __init__(self):
            self.gdi32 = FakeGdi32()
            self.user32 = FakeUser32()

    class FakeCtypes:
        def __init__(self):
            self.windll = FakeWindll()

    monkeypatch.setitem(sys.modules, "ctypes", FakeCtypes())

    result = installer.install_fonts()

    assert {Path(p).name for p in calls["add_font"]} == {
        "NotoSansKR-Regular.ttf",
        "NotoSansKR-Bold.ttf",
    }
    assert len(calls["broadcast"]) == 1
    hwnd_broadcast, wm_fontchange = calls["broadcast"][0][0], calls["broadcast"][0][1]
    assert hwnd_broadcast == 0xFFFF
    assert wm_fontchange == 0x001D
    assert len(result) == 2  # 즉시 반영 실패 여부와 무관하게 설치 결과는 그대로 반환


def test_install_fonts_succeeds_even_if_font_refresh_raises(tmp_path, monkeypatch):
    fake_user_dir = tmp_path / "user_fonts"
    monkeypatch.setattr(installer, "_user_font_dir", lambda: fake_user_dir)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg_module())

    class BrokenCtypes:
        windll = None  # windll.gdi32 접근 시 AttributeError

    monkeypatch.setitem(sys.modules, "ctypes", BrokenCtypes())

    result = installer.install_fonts()

    assert len(result) == 2
    for path in result:
        assert path.exists()


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


# ---- 시험 격리: 실제 Windows 계정 -----------------------------------------


def _read_user_font_values() -> dict:
    """글꼴 키가 있는지와, 값마다 (데이터, 형식). 복원이 원래 형식과 키의 유무까지 되돌릴 수 있게 함께 읽는다."""
    import winreg

    values: dict = {"key_exists": True}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, installer._REG_KEY) as key:
            for name in installer._REG_VALUE_NAMES:
                try:
                    values[name] = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    values[name] = None
    except FileNotFoundError:
        values = {"key_exists": False, **dict.fromkeys(installer._REG_VALUE_NAMES)}
    return values


if sys.platform == "win32":
    import winreg as _winreg

    # 격리 픽스처가 시험 중에 진짜 쓰기 함수를 바꾸므로, 복원에는 모듈을 읽을 때 잡아 둔 원래 함수를 쓴다
    _REAL_CREATE_KEY_EX = _winreg.CreateKeyEx
    _REAL_SET_VALUE_EX = _winreg.SetValueEx


def _restore_user_font_values(before: dict) -> None:
    import winreg

    if _read_user_font_values() == before:
        return
    access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
    with _REAL_CREATE_KEY_EX(winreg.HKEY_CURRENT_USER, installer._REG_KEY, 0, access) as key:
        for name in installer._REG_VALUE_NAMES:
            if before[name] is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                data, kind = before[name]
                _REAL_SET_VALUE_EX(key, name, 0, kind, data)
        subkeys, value_count, _ = winreg.QueryInfoKey(key)
    if not before["key_exists"] and subkeys == 0 and value_count == 0:
        # 시험 전에 없던 키가 비어 남았으면 지운다. 다른 값이 생겼으면 손대지 않는다
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, installer._REG_KEY)


@pytest.mark.skipif(sys.platform != "win32", reason="실제 Windows 레지스트리와 GDI 글꼴 표가 있어야 한다")
def test_font_install_during_tests_leaves_user_registry_and_session_fonts_alone():
    # 2026-10-16 회사 PC 실측: 격리 픽스처가 글꼴 폴더만 임시 폴더로 돌려, 백엔드 전체 시험 뒤 사용자 계정의
    # HKCU 글꼴 등록 2건이 pytest 임시 폴더를 가리켰다. 임시 폴더가 지워지면 등록이 끊기고, 앱이 사용자 폴더에
    # 설치한 PC라면 정상 등록이 덮인다. 세션 글꼴 표 추가와 WM_FONTCHANGE 방송도 실제 데스크톱에 나간다.
    # 이 시험은 레지스트리와 세션 글꼴 표만 관측한다. 방송은 관측할 수단이 없어 픽스처의 대체에만 기댄다
    import ctypes

    before = _read_user_font_values()
    try:
        paths = installer.install_fonts()
        after = _read_user_font_values()
        # RemoveFontResourceW는 세션 글꼴 표에 그 파일이 있었을 때만 0이 아닌 값을 낸다(있었다면 함께 지운다)
        added = [p.name for p in paths if ctypes.windll.gdi32.RemoveFontResourceW(str(p.resolve()))]
    finally:
        _restore_user_font_values(before)
    assert after == before
    assert added == []
