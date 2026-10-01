"""내보내기 파일 처리 (설계서 7.1).

- 같은 파일 시스템의 임시 폴더에서 완성한 뒤 덮어쓰기 없이 게시한다
- 기존 파일을 덮어쓰지 않고 v001, v002 새 버전으로 저장한다
  (사용자가 PowerPoint에서 직접 고친 수정분의 소실 방지)
- deck.json은 읽기만 하고 절대 고치지 않는다
"""

import hashlib
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from slidecaptain.export import history
from slidecaptain.export.locking import (export_directory_lock, pinned_export_directory,
                                        require_directory_identity, require_publication_identity)
from slidecaptain.export.pptx_writer import write_pptx
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck
from slidecaptain.models.export_qualification import ExportProvenance
from slidecaptain.models.preset import Preset, apply_overrides
from slidecaptain.pipeline.quality import assess_quality, require_export_allowed
from slidecaptain.storage.file_store import load_source_directory

_VERSION_RE = re.compile(r"(\d{3,})\.(?:pptx|quality\.json|provenance\.json)")
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_title(title: str) -> str:
    """Windows에서 쓸 수 없는 파일명 문자를 밑줄로 바꾼다 (덱 제목에 콜론이 흔하다)."""
    return _INVALID_FILENAME_CHARS.sub("_", title).strip() or "deck"


def _next_version_path(out_dir: Path, title: str, reader=None) -> Path:
    prefix = f"{title}_v"
    if reader is None:
        names = [p.name for p in out_dir.iterdir()]
    else:
        with reader.scan() as entries:
            names = [entry.name for entry in entries]
    existing = [int(m.group(1)) for name in names
                if name.startswith(prefix) and (m := _VERSION_RE.fullmatch(name[len(prefix):]))]
    next_no = max(existing, default=0) + 1
    path = out_dir / f"{title}_v{next_no:03d}.pptx"
    # 백스톱: 어떤 사유로든 스캔이 놓친 파일이 있으면 절대 그 경로를 돌려주지 않는다
    while (os.path.lexists(path) or os.path.lexists(path.with_suffix(".quality.json"))
           or os.path.lexists(path.with_suffix(".provenance.json"))):
        next_no += 1
        path = out_dir / f"{title}_v{next_no:03d}.pptx"
    return path


@contextmanager
def _staging_directory(out_dir: Path, identity: tuple):
    # Retain private staging instead of deleting by a mutable pathname. Comparing
    # an inode before unlink still lets another process replace that name between
    # the check and deletion; portable Python has no conditional inode unlink.
    # Staging is hidden, local, mode 0700 and never treated as a published export.
    # Cleanup requires a separately authorized maintenance operation.
    path = Path(tempfile.mkdtemp(prefix=".slidecaptain-export-", dir=out_dir))
    require_directory_identity(out_dir, identity)
    stage_identity = history._directory_identity(path)
    owned = {}
    with pinned_export_directory(path, stage_identity) as reader:
        yield path, reader, owned, stage_identity


def _verify_published(reader, path: Path, signature: tuple, digest: str):
    actual_digest, actual_signature = history._read_regular(path, reader=reader, digest=True)
    # Linking changes ctime; inode, mode, size and mtime must remain original.
    if actual_signature[:5] != signature[:5] or actual_digest != digest:
        raise OSError("Published export file changed")


def _create_staged(reader, name: str, owned: dict):
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = (os.open(name, flags, 0o600, dir_fd=reader.fd) if reader.fd is not None
          else os.open(reader.path / name, flags, 0o600))
    try:
        if reader.windows is not None:
            reader.windows.verify_fd(fd, name)
        owned[name] = history._signature(os.fstat(fd))
        return fd
    except BaseException:
        os.close(fd)
        raise


def export_deck_data(
    deck: Deck,
    out_dir: str | Path,
    global_preset: Preset | None = None,
    *,
    final: bool = False,
    sources: dict[str, str] | None = None,
) -> Path:
    """초안 PPTX와 사전 점검 기록을 새 버전으로 쓴다. 덱은 고치지 않는다."""
    out_dir = Path(out_dir)

    preset = apply_overrides(global_preset or Preset(), deck.meta.preset_overrides)
    metrics = FontMetrics.load_default()
    plan = build_render_plan(deck, preset, metrics, sources=sources)
    quality = assess_quality(deck, preset, plan, sources=sources)
    require_export_allowed(quality, final=final)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = out_dir.resolve(strict=True)
    identity = history._directory_identity(out_dir)
    # Render outside the publication lock, while source reads and cleanup bind
    # to the original staging descriptor.
    with _staging_directory(out_dir, identity) as (tmp, staging, owned, stage_identity):
        tmp_file = tmp / "deck.pptx"
        fd = _create_staged(staging, tmp_file.name, owned)
        with os.fdopen(fd, "w+b") as stream:
            write_pptx(plan, stream)
            stream.flush()
            owned[tmp_file.name] = history._signature(os.fstat(stream.fileno()))
        require_directory_identity(out_dir, identity)
        require_directory_identity(tmp, stage_identity)
        if not history._still_same(tmp_file, owned[tmp_file.name], staging):
            raise OSError("Staged export file changed")
        digest, owned[tmp_file.name] = history._read_regular(tmp_file, reader=staging, digest=True)
        quality.artifact_sha256 = digest
        tmp_quality = tmp / "deck.quality.json"
        fd = _create_staged(staging, tmp_quality.name, owned)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            if staging.windows is not None:
                staging.windows.verify_fd(stream.fileno(), tmp_quality.name)
            owned[tmp_quality.name] = history._signature(os.fstat(stream.fileno()))
            stream.write(quality.model_dump_json(indent=2))
        # Track the completed bytes, then require them unchanged before linking.
        raw_quality, owned[tmp_quality.name] = history._read_regular(tmp_quality, reader=staging)
        tmp_provenance = tmp / 'deck.provenance.json'
        provenance = ExportProvenance(rule_version='export-provenance-v1', producer_id='slidecaptain',
                                      producer_run_id=uuid.uuid4().hex, input_fingerprint=quality.input_fingerprint,
                                      artifact_sha256=quality.artifact_sha256)
        fd = _create_staged(staging, tmp_provenance.name, owned)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(provenance.model_dump_json(indent=2))
        raw_provenance, owned[tmp_provenance.name] = history._read_regular(tmp_provenance, reader=staging)
        expected_hashes = {tmp_file.name: quality.artifact_sha256,
                           tmp_quality.name: hashlib.sha256(raw_quality).hexdigest(),
                           tmp_provenance.name: hashlib.sha256(raw_provenance).hexdigest()}
        with export_directory_lock(out_dir) as reader:
            require_publication_identity(reader, identity)
            final_path = _next_version_path(out_dir, _safe_title(deck.meta.title), reader)
            require_publication_identity(reader, identity)
            publication = ((tmp_quality, final_path.with_suffix(".quality.json")),
                           (tmp_file, final_path),
                           (tmp_provenance, final_path.with_suffix('.provenance.json')))
            for source, destination in publication:
                require_publication_identity(reader, identity)
                if not history._still_same(source, owned[source.name], staging):
                    raise OSError("Staged export file changed")
                if reader.fd is not None:
                    os.link(source.name, destination.name, src_dir_fd=staging.fd,
                            dst_dir_fd=reader.fd, follow_symlinks=False)
                else:
                    os.link(source, destination, follow_symlinks=False)
                _verify_published(reader, destination, owned[source.name], expected_hashes[source.name])
                require_publication_identity(reader, identity)
            # Recheck the whole set after the last link, including its canonical
            # public path, before reporting a successfully published export.
            for source, destination in publication:
                _verify_published(reader, destination, owned[source.name], expected_hashes[source.name])
            require_publication_identity(reader, identity)
    return final_path


def export_deck(
    deck_path: str | Path,
    out_dir: str | Path,
    global_preset: Preset | None = None,
    *,
    final: bool = False,
) -> Path:
    deck_path = Path(deck_path)
    deck = Deck.model_validate_json(deck_path.read_text(encoding="utf-8"))
    sources = load_source_directory(deck_path.parent / "sources")
    return export_deck_data(deck, out_dir, global_preset, final=final, sources=sources)
