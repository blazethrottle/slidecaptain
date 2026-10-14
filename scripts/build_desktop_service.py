"""Build the self-contained desktop service for the current OS outside the checkout.

CLI executables and authentication profiles are not bundled. The official SDK's
Python adapter is included; users install native official CLIs separately.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path):
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Desktop build output must be outside the repository')
    if output.exists():
        raise FileExistsError('Choose a new output directory; existing files are preserved')
    ui = ROOT / 'frontend' / 'dist'
    if not (ui / 'index.html').is_file():
        raise ValueError('Run the frontend build first')
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='slidecaptain-freeze-') as temp:
        directory = Path(temp)
        entry = directory / 'desktop_entry.py'
        entry.write_text('from slidecaptain.desktop_service import main\nraise SystemExit(main())\n')
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
                        '--name', 'slidecaptain-service', '--distpath', str(output),
                        '--workpath', str(directory / 'build'), '--specpath', str(directory),
                        '--paths', str(ROOT / 'backend'), '--collect-data', 'slidecaptain',
                        '--copy-metadata', 'claude-agent-sdk', '--collect-submodules', 'uvicorn',
                        '--add-data', f'{ui}:slidecaptain/ui', str(entry)], check=True, cwd=ROOT)
    resources = output / 'slidecaptain-service'
    # No CLI redistributable is approved in this technical spike.
    if any(p.name in {'claude', 'claude.exe', 'codex', 'codex.exe'} for p in resources.rglob('*')):
        raise ValueError('An official CLI was unexpectedly included')
    files = []
    for source in sorted(resources.rglob('*')):
        if source.is_file():
            with source.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            files.append({'file': str(source.relative_to(resources)), 'sha256': digest})
    manifest = {'product': 'slidecaptain-service', 'platform': sys.platform, 'python': sys.version.split()[0],
                'ui_included': True, 'official_cli_included': False, 'files': files}
    (output / 'desktop-build.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(resources)
    return resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args.out_dir)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Desktop service build failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
