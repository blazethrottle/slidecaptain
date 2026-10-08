"""실제 프로세스 관통 시험의 서비스 실행기 (개정판 D2b-6, 계획서 6절 D2b-6). 시험 전용이다.

데스크톱 서비스(`slidecaptain.desktop_service`)를 그대로 띄우되, 장 적용의 한 지점에서 관문 파일이 생길 때까지
멈추게 한다. 시험은 멈춘 것을 확인한 뒤 이 프로세스를 SIGKILL로 끊는다. 제품 코드에는 시험 장치를 두지 않는다.

환경 변수
- HARNESS_PAUSE_AT: apply(③ 직전, 결과는 원장에 있고 적용 전) 또는 save(④ 적용 대상 ETag 기록 뒤 ⑤ 저장 전).
  비우면 멈추지 않는다
- HARNESS_PAUSED: 멈췄음을 알리는 파일 경로
- HARNESS_UI: 화면 폴더(시험이 만든 빈 index.html 폴더). 화면 빌드 여부와 무관하게 서비스를 띄운다
"""

import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _in_apply() -> bool:
    return any(frame.name == "_apply_chapter" for frame in traceback.extract_stack())


def _pause() -> None:
    Path(os.environ["HARNESS_PAUSED"]).write_text("paused", encoding="utf-8")
    while True:  # 시험이 SIGKILL로 끊는다
        time.sleep(0.05)


def _install() -> None:
    from slidecaptain import desktop_service
    from slidecaptain.storage.file_store import FileProjectStore

    ui = os.environ.get("HARNESS_UI")
    if ui:
        desktop_service._find_ui_dir = lambda: Path(ui)
    point = os.environ.get("HARNESS_PAUSE_AT", "")
    if point == "apply":
        original_load = FileProjectStore.load_deck_with_etag

        def load(self, name):
            if _in_apply():
                _pause()
            return original_load(self, name)
        FileProjectStore.load_deck_with_etag = load
    elif point == "save":
        original_save = FileProjectStore.save_deck

        def save(self, name, deck, *args, **kwargs):
            if _in_apply():
                _pause()
            return original_save(self, name, deck, *args, **kwargs)
        FileProjectStore.save_deck = save


if __name__ == "__main__":
    _install()
    from slidecaptain.desktop_service import main
    sys.exit(main())
