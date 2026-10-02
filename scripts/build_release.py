"""Build a private-data-free wheel and a standalone local application ZIP."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WINDOWS_LAUNCHER = '''@echo off
cd /d "%~dp0"
py -3.13 --version >nul 2>&1
if errorlevel 1 goto fallback
py -3.13 release_launcher.py
goto done
:fallback
python release_launcher.py
:done
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
'''

MAC_LAUNCHER = '''#!/bin/sh
cd "$(dirname "$0")" || exit 1
if command -v python3.13 >/dev/null 2>&1; then
  python3.13 release_launcher.py
elif command -v uv >/dev/null 2>&1; then
  python_path=$(uv python find '>=3.13' 2>/dev/null)
  if [ -n "$python_path" ]; then
    "$python_path" release_launcher.py
  else
    echo "Python 3.13+ is required. See START-HERE.txt."
    exit 1
  fi
else
  python3 release_launcher.py
fi
result=$?
if [ "$result" -ne 0 ]; then
  printf 'Press Enter to close: '
  read -r answer
fi
exit "$result"
'''

GUIDE = '''SlideCaptain {version} 개인용 로컬 앱

1. ZIP 전체를 쓰기 가능한 새 폴더에 압축 해제합니다. ZIP 안에서 직접 실행하지 마세요.
2. Python 3.13 이상이 필요합니다. Windows는 python.org 설치 시 Python launcher와 PATH를 활성화하세요.
   macOS는 python.org의 Python 3.13 설치본 또는 uv로 이미 설치된 Python 3.13 이상을 사용합니다.
   uv만 설치했다면 먼저 터미널에서 uv python install 3.13을 실행하세요.
3. Windows: SlideCaptain.bat, macOS: SlideCaptain.command를 실행합니다.
   macOS가 다운로드 파일을 차단하면 터미널에서 해당 폴더로 이동해 sh SlideCaptain.command를 실행하세요.
4. 최초 실행은 인터넷으로 고정 버전 의존성을 설치하여 몇 분 걸릴 수 있습니다.
   다음 실행은 같은 폴더의 .venv를 재사용합니다. 브라우저가 http://127.0.0.1:8765를 엽니다.
5. 앱 종료는 실행 창에서 Ctrl+C입니다. 이 PC에서만 접속할 수 있습니다.

프로젝트는 ~/slidecaptain-projects에 저장합니다. 릴리스 폴더와 별도이므로 업데이트 후에도 유지됩니다.
AI는 앱 안에서 연결한 계정을 사용합니다. ZIP에는 사용자 프로젝트나 로그인 정보가 없습니다.
AI 로그인의 공식 연결과 실제 호출은 각 사용자 계정에서 별도로 진행해야 합니다.
ChatGPT 연결에는 별도로 설치된 네이티브 Codex CLI가 필요합니다.
공식 설치 안내: https://developers.openai.com/codex/cli/
Windows에서는 .cmd/.bat 대신 codex.exe를 사용하세요. 자동 설치하지 않습니다.
설치 후 실행 파일을 찾지 못하면 SLIDECAPTAIN_CODEX_CLI에 네이티브 실행 파일 경로를 지정하세요.
상세 연결 안내: https://github.com/blazethrottle/slidecaptain/blob/main/README.md
PowerPoint 제출본은 앱의 렌더 및 독립 검수 관문을 계속 따릅니다.

업데이트: 기존 앱을 Ctrl+C로 종료하고 새 ZIP을 새 폴더에 풉니다. 기존 .venv를 복사하지 마세요.
새 폴더의 시작 파일을 실행하면 기존 프로젝트 폴더를 그대로 사용합니다.
8765 포트 충돌 또는 이전 버전 실행 메시지가 나오면 기존 실행 창을 종료하세요.
기존 프로젝트 폴더를 삭제하지 마세요. 앱 설치는 Python이나 다른 서버를 자동 종료하지 않습니다.

릴리스 무결성은 manifest.json의 wheel/requirements SHA-256으로 확인합니다.
Python이 없어 앱이 시작되지 않으면 Python 3.13 이상 설치와 위 사전 준비를 확인하세요.
'''


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage_backend(root, stage):
    """Copy only Git-index-listed package inputs, using current working bytes."""
    result = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", "--",
                                      "backend/slidecaptain", "backend/pyproject.toml"])
    for relative in result.decode("utf-8").split("\0"):
        if not relative:
            continue
        source = root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"빌드 입력이 일반 파일이 아닙니다: {relative}")
        target = stage / Path(relative).relative_to("backend")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    if not (stage / "pyproject.toml").is_file():
        raise ValueError("추적된 backend/pyproject.toml이 없습니다.")
    ui = root / "frontend" / "dist"
    if not (ui / "index.html").is_file():
        raise ValueError("먼저 npm --prefix frontend run build로 UI를 빌드하세요.")
    for source in ui.rglob("*"):
        if source.is_symlink():
            raise ValueError("UI 빌드에 심볼릭 링크를 포함할 수 없습니다.")
    shutil.copytree(ui, stage / "slidecaptain" / "ui")


def wheel_version(wheel):
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        for line in archive.read(metadata_name).decode("utf-8").splitlines():
            if line.startswith("Version: "):
                return line.removeprefix("Version: ")
    raise ValueError("wheel 버전을 찾지 못했습니다.")


def write_zip(bundle, destination):
    # Exclusive creation prevents accidentally overwriting an existing release.
    with destination.open("xb") as output:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.iterdir()):
                info = zipfile.ZipInfo(path.name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100755 if path.suffix == ".command" else 0o100644) << 16
                archive.writestr(info, path.read_bytes())


def build_release(root, out_dir):
    root, out_dir = root.resolve(), out_dir.resolve()
    if out_dir == root or root in out_dir.parents:
        raise ValueError("릴리스 출력은 저장소 밖의 폴더를 지정하세요.")
    lock = root / "backend" / "requirements-release.txt"
    if not lock.is_file():
        raise ValueError("검증한 backend/requirements-release.txt가 필요합니다.")
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("릴리스 wheel 빌드에는 uv가 필요합니다.")
    source_commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="slidecaptain-release-") as temporary:
        temp = Path(temporary)
        stage, bundle = temp / "backend", temp / "bundle"
        stage.mkdir()
        bundle.mkdir()
        stage_backend(root, stage)
        subprocess.run([uv, "build", "--wheel", "--out-dir", str(bundle), str(stage)], check=True)
        wheels = list(bundle.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("릴리스 wheel이 정확히 하나여야 합니다.")
        wheel = wheels[0]
        version = wheel_version(wheel)
        requirements = bundle / "requirements.txt"
        shutil.copyfile(lock, requirements)
        shutil.copyfile(root / "scripts" / "release_launcher.py", bundle / "release_launcher.py")
        (bundle / "SlideCaptain.bat").write_bytes(WINDOWS_LAUNCHER.replace("\n", "\r\n").encode("ascii"))
        (bundle / "SlideCaptain.command").write_text(MAC_LAUNCHER, encoding="ascii")
        (bundle / "START-HERE.txt").write_text(GUIDE.format(version=version), encoding="utf-8")
        manifest = {"product": "SlideCaptain", "version": version, "source_commit": source_commit,
                    "wheel": wheel.name, "wheel_sha256": digest(wheel),
                    "requirements": requirements.name, "requirements_sha256": digest(requirements)}
        (bundle / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out_dir.mkdir(parents=True, exist_ok=True)
        destination = out_dir / f"slidecaptain-{version}-local.zip"
        wheel_output = out_dir / wheel.name
        if destination.exists() or wheel_output.exists():
            raise FileExistsError("같은 이름의 릴리스가 있습니다. 새 출력 폴더를 지정하세요.")
        with wheel_output.open("xb") as output:
            output.write(wheel.read_bytes())
        write_zip(bundle, destination)
        return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", "--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build_release(ROOT, args.out_dir))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"릴리스 빌드 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
