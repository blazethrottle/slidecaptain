"""Exercise an installed release in an isolated folder without AI calls."""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def verify(python: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="slidecaptain-installed-") as folder:
        data = (Path(folder) / "projects").resolve()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        def request(path, body=None, method=None, headers=None):
            payload = None if body is None else json.dumps(body).encode("utf-8")
            req = urllib.request.Request(base + path, data=payload, method=method,
                headers={"Content-Type": "application/json", "X-Requested-With": "SlideCaptain", **(headers or {})})
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read(), response.headers

        # Font installation is separately tested; the release smoke must not change
        # the CI runner's or the developer's user font directories.
        code = "import sys; from slidecaptain.fonts import installer; installer.ensure_fonts=lambda: 'already-installed'; from slidecaptain.__main__ import main; sys.exit(main(sys.argv[1:]))"
        with (Path(folder) / "server.log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen([str(python.absolute()), "-c", code, "serve", "--port", str(port), "--data-dir", str(data)], cwd=folder, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("Installed server exited: " + (Path(folder) / "server.log").read_text(encoding="utf-8"))
                    try:
                        health = json.loads(request("/api/health")[0])
                        break
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Installed server did not become ready")
                assert health["product"] == "slidecaptain" and health["ui_ready"]
                html = request("/")[0].decode("utf-8")
                assert '<div id="root">' in html and "/assets/" in html
                import re
                assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
                assert assets and all(request(asset)[0] for asset in assets)
                request("/api/projects", {"name": "release-smoke", "title": "Release smoke"})
                raw, headers = request("/api/projects/release-smoke/deck")
                deck = json.loads(raw)
                deck["structure"] = {"chapters": [{"id": "cover", "topic": "Release smoke", "template": "cover"}]}
                deck["slides"] = [{"chapter_id": "cover", "slots": {"template": "cover", "title": "Release smoke"}}]
                request("/api/projects/release-smoke/deck", deck, "PUT", {"If-Match": headers["ETag"]})
                saved = json.loads(request("/api/projects/release-smoke/deck")[0])
                assert len(saved["slides"]) == 1
                assert saved["slides"][0]["chapter_id"] == "cover"
                assert saved["slides"][0]["slots"]["title"] == "Release smoke"
                assert json.loads(request("/api/projects/release-smoke/snapshots")[0])
                output = json.loads(request("/api/projects/release-smoke/export", {})[0])
                pptx = Path(output["path"])
                assert pptx.is_file() and pptx.is_relative_to(data)
                with zipfile.ZipFile(pptx) as archive:
                    assert "ppt/slides/slide1.xml" in archive.namelist()
                assert not output["quality"]["final_export_allowed"]
                assert json.loads(request("/api/projects/release-smoke/exports")[0])
                print(json.dumps({"version": health["version"], "ui": "passed", "assets": len(assets), "save_snapshot_export_history": "passed", "ai_calls": 0}))
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    verify(parser.parse_args().python)
