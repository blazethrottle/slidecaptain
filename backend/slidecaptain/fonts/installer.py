"""Noto Sans KR 동봉 폰트의 감지와 사용자 권한 설치.

폭 계산은 번들 수치로 폰트 없이도 동작하므로, 설치는 화면 표시(미리보기, PowerPoint)의
올바름을 위한 것이다. 설치 실패는 앱 동작을 막지 않는다 (호출 측에서 경고로 처리).
"""

import os
import shutil
import sys
from importlib import resources
from pathlib import Path

_BUNDLED_FILENAMES = ("NotoSansKR-Regular.ttf", "NotoSansKR-Bold.ttf")

_REG_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
_REG_VALUE_NAMES = ("Noto Sans KR (TrueType)", "Noto Sans KR Bold (TrueType)")


def _bundled_font_paths() -> list[Path]:
    paths: list[Path] = []
    for filename in _BUNDLED_FILENAMES:
        ref = resources.files("slidecaptain.fonts").joinpath("assets", filename)
        with resources.as_file(ref) as path:
            paths.append(path)
    return paths


def _user_font_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts"
    if sys.platform == "darwin":
        return Path.home() / "Library/Fonts"
    return Path.home() / ".local/share/fonts"


def _system_font_dirs() -> list[Path]:
    if sys.platform == "win32":
        return [Path("C:/Windows/Fonts")]
    if sys.platform == "darwin":
        return [Path("/Library/Fonts")]
    return []


def font_installed() -> bool:
    for font_dir in (_user_font_dir(), *_system_font_dirs()):
        if font_dir.exists() and any(font_dir.glob("NotoSansKR*")):
            return True
    return False


def install_fonts() -> list[Path]:
    user_dir = _user_font_dir()
    user_dir.mkdir(parents=True, exist_ok=True)

    installed_paths: list[Path] = []
    for src in _bundled_font_paths():
        dest = user_dir / src.name
        shutil.copyfile(src, dest)
        installed_paths.append(dest)

    if sys.platform == "win32":
        import winreg

        # CreateKeyEx는 키가 없으면 만든다: 사용자 폰트를 한 번도 설치한 적 없는 계정은
        # HKCU에 이 Fonts 키 자체가 없을 수 있고, 그 경우 OpenKey는 FileNotFoundError를 낸다.
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            for value_name, path in zip(_REG_VALUE_NAMES, installed_paths):
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, str(path.resolve()))

        _refresh_windows_fonts(installed_paths)

    return installed_paths


def _refresh_windows_fonts(paths: list[Path]) -> None:
    """설치한 폰트를 재로그온 없이 즉시 반영 시도한다. 즉시 반영 시도이며 실패 시
    재로그온 후 적용된다 (설치 자체는 이 함수의 성패와 무관하게 성공으로 취급한다)."""
    try:
        import ctypes

        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        for path in paths:
            gdi32.AddFontResourceW(str(path.resolve()))

        HWND_BROADCAST = 0xFFFF
        WM_FONTCHANGE = 0x001D
        SMTO_ABORTIFHUNG = 0x0002
        user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_FONTCHANGE, 0, 0, SMTO_ABORTIFHUNG, 1000, None
        )
    except Exception:
        pass


def ensure_fonts() -> str:
    if font_installed():
        return "already"
    install_fonts()
    return "installed"
