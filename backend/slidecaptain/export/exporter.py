"""내보내기 파일 처리 (설계서 7.1).

- 저장은 ASCII 임시 경로에서 수행한 뒤 최종 위치로 이동한다 (한글 경로 안전)
- 기존 파일을 덮어쓰지 않고 v001, v002 새 버전으로 저장한다
  (사용자가 PowerPoint에서 직접 고친 수정분의 소실 방지)
- deck.json은 읽기만 하고 절대 고치지 않는다
"""

import re
import shutil
import tempfile
from pathlib import Path

from slidecaptain.export.pptx_writer import write_pptx
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset, apply_overrides

_VERSION_RE = re.compile(r"_v(\d{3,})\.pptx$")
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_title(title: str) -> str:
    """Windows에서 쓸 수 없는 파일명 문자를 밑줄로 바꾼다 (덱 제목에 콜론이 흔하다)."""
    return _INVALID_FILENAME_CHARS.sub("_", title).strip() or "deck"


def _next_version_path(out_dir: Path, title: str) -> Path:
    prefix = f"{title}_v"
    existing = [
        int(m.group(1))
        for p in out_dir.iterdir()
        if p.name.startswith(prefix) and (m := _VERSION_RE.search(p.name))
    ]
    next_no = max(existing, default=0) + 1
    path = out_dir / f"{title}_v{next_no:03d}.pptx"
    # 백스톱: 어떤 사유로든 스캔이 놓친 파일이 있으면 절대 그 경로를 돌려주지 않는다
    while path.exists():
        next_no += 1
        path = out_dir / f"{title}_v{next_no:03d}.pptx"
    return path


def export_deck_data(
    deck: Deck,
    out_dir: str | Path,
    global_preset: Preset | None = None,
) -> Path:
    """메모리의 덱을 새 버전 파일로 내보낸다. 덱 데이터는 절대 고치지 않는다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    preset = apply_overrides(global_preset or Preset(), deck.meta.preset_overrides)
    metrics = FontMetrics.load_default()
    plan = build_render_plan(deck, preset, metrics)

    final_path = _next_version_path(out_dir, _safe_title(deck.meta.title))
    # 임시 폴더에서 쓴 뒤 이동: 저장 도중 실패해도 exports/에 깨진 파일이 남지 않는다
    with tempfile.TemporaryDirectory(prefix="slidecaptain_") as tmp:
        tmp_file = Path(tmp) / "deck.pptx"
        write_pptx(plan, tmp_file)
        shutil.move(str(tmp_file), str(final_path))
    return final_path


def export_deck(
    deck_path: str | Path,
    out_dir: str | Path,
    global_preset: Preset | None = None,
) -> Path:
    deck = Deck.model_validate_json(Path(deck_path).read_text(encoding="utf-8"))
    return export_deck_data(deck, out_dir, global_preset)
