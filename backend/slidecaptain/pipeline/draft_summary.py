"""보존본 복원 전 차이 요약 (개정판 D3c-6, 계획 4.8의 E7, D2a 이월 (17)).

보존본을 복원하면 저장본 전체가 보존본으로 바뀐다(보고 목적 화면의 보존본은 보고 정보만). 사용자가 무엇이 바뀌는지 모르고
복원하면 다른 곳의 변경이 사라진다. 복원 전에 서버 저장본과 비교해 바뀐 장, 더해지는 장, 빠지는 장, 직접 수정이 다른 장,
그리고 보고 정보, 장 순서, 구성 계획의 차이 유무를 돌려준다. 보존본은 검증 없이 원문을 담으므로 지금 형식으로 읽히지 않으면
요약하지 않는다(복원도 같은 이유로 거절된다).
"""

from pydantic import BaseModel, ValidationError

from slidecaptain.models.deck import Deck
from slidecaptain.models.report_purpose import PURPOSE_SCREEN_FIELDS


class ChapterLabel(BaseModel):
    id: str
    label: str  # "2장 시장 현황"


class DraftSummary(BaseModel):
    readable: bool  # 지금 형식으로 읽혔는가. 거짓이면 나머지 칸은 비어 있다
    purpose_only: bool  # 보고 목적 화면의 보존본: 복원은 보고 정보만 바꾼다
    changed_chapters: list[ChapterLabel]  # 양쪽에 있고 장 정의나 슬라이드 내용이 다른 장
    added_chapters: list[ChapterLabel]  # 보존본에만 있는 장(복원하면 생긴다)
    removed_chapters: list[ChapterLabel]  # 저장본에만 있는 장(복원하면 사라진다)
    direct_edit_chapters: list[ChapterLabel]  # 위치와 서식 수정이 다른 장
    report_info_changed: bool
    order_changed: bool
    story_plan_changed: bool
    # D3c-6 리뷰 G4, G10: 복원은 덱 전체를 쓰므로 디자인 값과 문서 검토 기록의 차이도 알린다. 저장본을 읽지 못하면
    # 복원은 보존본 전체를 쓰고(보고 목적 보존본도) 요약의 장 목록은 모두 "생기는 장"이 된다
    design_changed: bool = False
    review_changed: bool = False
    current_readable: bool = True


def _labels(deck: Deck) -> dict[str, str]:
    return {c.id: f"{i + 1}장 {c.topic}" for i, c in enumerate(deck.structure.chapters)}


def _slide_parts(deck: Deck) -> dict[str, tuple[dict, dict]]:
    """장마다 (직접 수정을 뺀 슬라이드, 직접 수정)."""
    parts = {}
    for slide in deck.slides:
        body = slide.model_dump(mode="json")
        edits = body.pop("direct_edits", {}) or {}
        parts[slide.chapter_id] = (body, edits)
    return parts


def summarize_draft(current: Deck | None, draft: object, source: str) -> DraftSummary:
    empty = DraftSummary(readable=False, purpose_only=source == "purpose" and current is not None, changed_chapters=[],
                         added_chapters=[], removed_chapters=[], direct_edit_chapters=[], report_info_changed=False,
                         order_changed=False, story_plan_changed=False, current_readable=current is not None)
    try:
        restored = Deck.model_validate(draft)
    except (ValidationError, ValueError, TypeError):
        return empty
    now_meta = current.meta.model_dump(mode="json") if current else {}
    then_meta = restored.meta.model_dump(mode="json")
    if source == "purpose" and current is not None:  # 저장본을 읽지 못하면 복원은 보존본 전체를 쓴다(file_store.restore_draft)
        changed = any(now_meta.get(k) != then_meta.get(k) for k in PURPOSE_SCREEN_FIELDS)
        return empty.model_copy(update={"readable": True, "report_info_changed": changed})
    design_changed = now_meta.pop("preset_overrides", None) != then_meta.pop("preset_overrides", None)  # 디자인 값은 따로 알린다
    review_now = current.document_review.model_dump(mode="json") if current and current.document_review else None
    review_then = restored.document_review.model_dump(mode="json") if restored.document_review else None
    now_labels = _labels(current) if current else {}
    then_labels = _labels(restored)
    now_chapters = {c.id: c.model_dump(mode="json") for c in current.structure.chapters} if current else {}
    then_chapters = {c.id: c.model_dump(mode="json") for c in restored.structure.chapters}
    now_slides = _slide_parts(current) if current else {}
    then_slides = _slide_parts(restored)
    common = [cid for cid in then_labels if cid in now_labels]
    changed, edited = [], []
    for cid in common:
        now_body, now_edits = now_slides.get(cid, (None, {}))
        then_body, then_edits = then_slides.get(cid, (None, {}))
        if now_chapters[cid] != then_chapters[cid] or now_body != then_body:
            changed.append(ChapterLabel(id=cid, label=then_labels[cid]))
        if now_edits != then_edits:
            edited.append(ChapterLabel(id=cid, label=then_labels[cid]))
    now_order = [cid for cid in now_labels if cid in then_labels]
    plan_now = current.structure.story_plan.model_dump(mode="json") if current and current.structure.story_plan else None
    plan_then = restored.structure.story_plan.model_dump(mode="json") if restored.structure.story_plan else None
    return DraftSummary(
        readable=True, purpose_only=False, changed_chapters=changed,
        added_chapters=[ChapterLabel(id=cid, label=label) for cid, label in then_labels.items() if cid not in now_labels],
        removed_chapters=[ChapterLabel(id=cid, label=label) for cid, label in now_labels.items() if cid not in then_labels],
        direct_edit_chapters=edited, report_info_changed=now_meta != then_meta, order_changed=now_order != common,
        story_plan_changed=plan_now != plan_then, design_changed=current is not None and design_changed,
        review_changed=current is not None and review_now != review_then, current_readable=current is not None)
