"""Standalone launcher shipped beside the wheel; uses only the Python stdlib."""

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser
from pathlib import Path

PRODUCT = "SlideCaptain"
PORT = 8765


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_manifest(folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("product") != PRODUCT or not isinstance(manifest.get("version"), str):
        raise ValueError("SlideCaptain 릴리스 정보가 올바르지 않습니다.")
    for name, digest_name in (("wheel", "wheel_sha256"), ("requirements", "requirements_sha256")):
        filename = manifest.get(name)
        if not isinstance(filename, str) or not filename or Path(filename).name != filename or "\\" in filename:
            raise ValueError("릴리스 파일 경로가 올바르지 않습니다.")
        path = folder / filename
        if not path.is_file() or sha256(path) != manifest.get(digest_name):
            raise ValueError(f"릴리스 파일 검증 실패: {filename}. ZIP을 다시 내려받아 주세요.")
    return manifest


def venv_python(folder):
    return folder / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def ensure_environment(folder, manifest):
    python = venv_python(folder)
    marker = folder / ".venv" / "slidecaptain-release.json"
    fingerprint = {key: manifest[key] for key in ("version", "wheel_sha256", "requirements_sha256")}
    try:
        if python.is_file() and json.loads(marker.read_text(encoding="utf-8")) == fingerprint:
            return python
    except (OSError, ValueError):
        pass
    print("최초 실행 환경을 준비합니다. 인터넷 연결이 필요합니다.", flush=True)
    # Reuse this release's environment after an interrupted install. Never touch user data.
    # uv-managed macOS CPython needs its original library-relative executable.
    # Windows venvs use copied launchers; POSIX uses links to the interpreter.
    venv.EnvBuilder(with_pip=True, symlinks=sys.platform != "win32").create(folder / ".venv")
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                    "-r", str(folder / manifest["requirements"])], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps",
                    "--force-reinstall", str(folder / manifest["wheel"])], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    marker.write_text(json.dumps(fingerprint), encoding="utf-8")
    return python


def read_health(port=PORT):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            return json.loads(response.read(65536))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def matches_release(health, manifest):
    return (isinstance(health, dict) and health.get("product") == "slidecaptain"
            and health.get("version") == manifest["version"] and health.get("ui_ready") is True)


def port_in_use(port=PORT):
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def run_release(folder, *, install_only=False, no_browser=False, port=PORT, data_dir=None):
    if sys.version_info < (3, 13):
        raise ValueError("Python 3.13 이상이 필요합니다. 시작 안내를 확인해 주세요.")
    manifest = load_manifest(folder)
    if not 1 <= port <= 65535:
        raise ValueError("포트는 1~65535 범위여야 합니다.")
    url = f"http://127.0.0.1:{port}"
    if install_only:
        ensure_environment(folder, manifest)
        return 0
    if port_in_use(port):
        if matches_release(read_health(port), manifest):
            if not no_browser:
                webbrowser.open(url)
            return 0
        raise ValueError(f"{port} 포트에 다른 서버 또는 이전 SlideCaptain이 실행 중입니다. "
                         "기존 실행 창에서 Ctrl+C로 종료한 뒤 다시 실행해 주세요.")
    python = ensure_environment(folder, manifest)
    command = [str(python), "-m", "slidecaptain", "serve", "--port", str(port)]
    if data_dir is not None:
        command.extend(["--data-dir", str(data_dir)])
    child = subprocess.Popen(command, cwd=folder)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if child.poll() is not None:
                if child.returncode == 75:  # 자료 폴더 잠금 (backend service_lock.EXIT_DATA_DIR_IN_USE)
                    raise ValueError("같은 자료 폴더를 다른 SlideCaptain이 사용하고 있습니다. 위의 안내를 확인해 주세요.")
                raise ValueError("SlideCaptain 서버가 시작 중 종료되었습니다. 위 오류를 확인해 주세요.")
            if matches_release(read_health(port), manifest):
                # A process that lost a port race must not claim another server.
                if child.poll() is not None:
                    raise ValueError("시작한 서버가 종료되었습니다. 포트 사용 상태를 확인하세요.")
                if not no_browser:
                    webbrowser.open(url)
                print("SlideCaptain 실행 중입니다. 종료하려면 이 창에서 Ctrl+C를 누르세요.", flush=True)
                return child.wait()
            time.sleep(0.5)
        raise ValueError("SlideCaptain 시작을 60초 동안 확인하지 못했습니다. 위 오류를 확인해 주세요.")
    finally:
        # Stop only the process started by this invocation, never an existing server.
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    try:
        return run_release(Path(__file__).resolve().parent, install_only=args.install_only,
                           no_browser=args.no_browser, port=args.port, data_dir=args.data_dir)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"SlideCaptain 실행 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
