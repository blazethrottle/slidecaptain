"""Fixed native PowerPoint renderer. Missing runtime is never a passing proof.

PowerPoint runs only on Windows. Images are produced by the server, never by a
client-declared renderer. Installed font inventory detects changes; it does not
prove which fallback glyph PowerPoint selected for each character.
"""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from PIL import Image
from slidecaptain.export.locking import ExportBusyError, export_directory_lock


class RenderUnavailable(ValueError):
    pass


class RenderFailed(ValueError):
    pass


MAX_PAGE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_PAGES = 200
_NATIVE_THREAD_LOCK = threading.Lock()


def validate_png(data: bytes) -> tuple[int, int]:
    if len(data) > MAX_PAGE_BYTES or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('렌더 페이지가 유효한 PNG가 아니거나 크기 한도를 초과했습니다.')
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if image.format != 'PNG' or not (1 <= width <= 10000 and 1 <= height <= 10000) or width * height > 20_000_000:
                raise ValueError('렌더 페이지 크기를 확인하지 못했습니다.')
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except Exception as exc:
        raise ValueError('렌더 페이지를 완전히 읽지 못했습니다.') from exc
    return width, height


def _hash_file(path: Path) -> str:
    before = path.stat()
    if not path.is_file() or path.is_symlink():
        raise RenderUnavailable('PowerPoint 환경 파일을 안전하게 확인하지 못했습니다.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RenderUnavailable('PowerPoint 환경 파일이 바뀌었습니다.')
    return digest.hexdigest()


def _runtime_paths() -> tuple[Path, Path]:
    if sys.platform != 'win32':
        raise RenderUnavailable('이 환경의 native PowerPoint 자동 렌더는 지원하지 않습니다. Windows PowerPoint 실기기에서 렌더해야 합니다.')
    import winreg
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    executable = None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE', 0, winreg.KEY_READ | view) as key:
                    executable = Path(winreg.QueryValue(key, None).strip('"'))
                    break
            except OSError:
                continue
        if executable is not None:
            break
    if executable is None or not executable.is_file() or not powershell.is_file():
        raise RenderUnavailable('Windows PowerPoint 또는 Windows PowerShell을 찾지 못했습니다.')
    return executable, powershell


def current_environment() -> dict[str, str]:
    executable, _ = _runtime_paths()
    roots = [Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'Fonts',
             Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Windows/Fonts']
    fonts = []
    for index, root in enumerate(roots):
        if root.exists():
            for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
                if path.suffix.casefold() in ('.ttf', '.otf', '.ttc'):
                    if len(fonts) >= 5000:
                        raise RenderUnavailable('설치 폰트 확인 한도를 초과했습니다.')
                    fonts.append((index, path.name, _hash_file(path)))
    if not fonts:
        raise RenderUnavailable('실제 설치 폰트 목록을 확인하지 못했습니다.')
    fonts_hash = hashlib.sha256(json.dumps(fonts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    result = {'renderer': 'Microsoft PowerPoint', 'operating_system': sys.getwindowsversion().__str__(),
              'executable_sha256': _hash_file(executable), 'installed_fonts_sha256': fonts_hash,
              'font_file_count': str(len(fonts))}
    result['fingerprint'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


_SCRIPT = r'''
param([string]$InputFile, [string]$OutputDir)
$ErrorActionPreference = 'Stop'
# Do not attach to or close a user's already running PowerPoint session.
if (Get-Process POWERPNT -ErrorAction SilentlyContinue) { throw 'PowerPoint is already running. Close it before server rendering.' }
$app = $null
$presentation = $null
try {
    $app = New-Object -ComObject PowerPoint.Application
    $presentation = $app.Presentations.Open($InputFile, -1, 0, 0)
    $width = 1920
    $height = [int][Math]::Round($width * $presentation.PageSetup.SlideHeight / $presentation.PageSetup.SlideWidth)
    $presentation.Export($OutputDir, 'PNG', $width, $height)
    $manifest = @{version=[string]$app.Version; build=[string]$app.Build; count=[int]$presentation.Slides.Count; width=$width; height=$height}
    $manifest | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $OutputDir 'environment.json') -Encoding UTF8
} finally {
    if ($presentation -ne $null) { $presentation.Close(); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation) }
    # COM is a singleton and a user may start it after the guard. Release only
    # our reference; never Quit an application whose process ownership is unproved.
    if ($app -ne $null) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($app) }
}
'''


def _render_powerpoint_unlocked(artifact: Path, destination: Path, expected_count: int) -> tuple[dict[str, str], list[bytes]]:
    if not 1 <= expected_count <= MAX_PAGES:
        raise RenderUnavailable('PowerPoint 렌더 페이지 한도(1~200)를 초과했습니다.')
    _, powershell = _runtime_paths()
    before = current_environment()
    source_hash = _hash_file(artifact)
    destination.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix='slidecaptain-native-') as directory:
        script = Path(directory) / 'render.ps1'
        script.write_text(_SCRIPT, encoding='utf-8-sig')
        try:
            completed = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-File', str(script),
                                        str(artifact.resolve()), str(destination.resolve())],
                                       timeout=120, capture_output=True, check=False)
        except subprocess.TimeoutExpired as exc:
            # subprocess.run terminates only our PowerShell child. Never kill a
            # user's PowerPoint by process name; COM cleanup is best effort.
            raise RenderFailed('PowerPoint 렌더 제한 시간을 초과했습니다. 생성한 초안은 보존했습니다.') from exc
        if completed.returncode != 0:
            raise RenderFailed('PowerPoint 렌더를 완료하지 못했습니다. 실행 중인 PowerPoint와 파일 접근 권한을 확인해 주세요.')
    try:
        metadata = json.loads((destination / 'environment.json').read_text(encoding='utf-8-sig'))
        if (type(metadata.get('count')) is not int or metadata['count'] != expected_count
                or type(metadata.get('width')) is not int or type(metadata.get('height')) is not int
                or not isinstance(metadata.get('version'), str) or not metadata['version'].strip()
                or not isinstance(metadata.get('build'), str) or not metadata['build'].strip()):
            raise ValueError('Missing native environment')
        paths = list(destination.glob('*.PNG')) + list(destination.glob('*.png'))
        paths = list({p.name: p for p in paths}.values())
        numbered = {}
        for path in paths:
            match = re.search(r'(\d+)\.png$', path.name, re.IGNORECASE)
            if match is None or int(match.group(1)) in numbered or path.is_symlink():
                raise ValueError('Unexpected page name')
            numbered[int(match.group(1))] = path
        if sorted(numbered) != list(range(1, expected_count + 1)):
            raise ValueError('Incomplete native page set')
        pages = []
        for number in range(1, expected_count + 1):
            path = numbered[number]
            if path.stat().st_size > MAX_PAGE_BYTES:
                raise ValueError('Page too large')
            data = path.read_bytes()
            if validate_png(data) != (metadata['width'], metadata['height']):
                raise ValueError('Native page size mismatch')
            pages.append(data)
            if sum(map(len, pages)) > MAX_TOTAL_BYTES:
                raise ValueError('Native pages too large')
        if current_environment() != before or _hash_file(artifact) != source_hash:
            raise ValueError('Environment changed')
    except (OSError, ValueError, TypeError) as exc:
        raise RenderFailed('PowerPoint 페이지 전체와 실제 환경을 대조하지 못했습니다.') from exc
    return {**before, 'powerpoint_version': str(metadata['version']), 'powerpoint_build': str(metadata['build'])}, pages


def render_powerpoint(artifact: Path, destination: Path, expected_count: int) -> tuple[dict[str, str], list[bytes]]:
    _runtime_paths()  # Missing runtimes do not create a lock directory.
    # PowerPoint COM is shared across projects and local app processes. Project
    # locks alone do not serialize it. Pin the OS lock with the same safe helper
    # used for export publication; this directory contains no user documents.
    directory = Path.home() / '.slidecaptain' / 'native-runtime'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not _NATIVE_THREAD_LOCK.acquire(timeout=5):
        raise RenderUnavailable('다른 프로젝트에서 PowerPoint를 렌더하고 있습니다. 완료 후 다시 시도해 주세요.')
    try:
        with export_directory_lock(directory):
            return _render_powerpoint_unlocked(artifact, destination, expected_count)
    except ExportBusyError as exc:
        raise RenderUnavailable('다른 프로젝트에서 PowerPoint를 렌더하고 있습니다. 완료 후 다시 시도해 주세요.') from exc
    finally:
        _NATIVE_THREAD_LOCK.release()
