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

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            for value_name, path in zip(_REG_VALUE_NAMES, installed_paths):
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, str(path.resolve()))

    return installed_paths


def ensure_fonts() -> str:
    if font_installed():
        return "already"
    install_fonts()
    return "installed"
