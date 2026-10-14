"""후보의 관련 입력 해시 (개정판 D2b-3, D3b-2, 계획 4.3).

원장의 relevance_hash 칸에 담는다(원장 형식은 바꾸지 않는다). 판정식 표지가 없는 행은 이전 빌드가 쓴 것이다.

- 구조안: "s1:<가>|<나>". (가)는 구조안 지시문과 응답 해석이 덱에서 읽는 값(제목, 보고 유형, 피보고자, 보고
  목적 값), (나)는 승인이 덮어쓰는 범위(structure, slides)다. (나)가 없으면 후보를 만든 뒤 재작성, 도식 추가,
  슬라이드 편집으로 바뀐 내용을 옛 후보 승인이 덮는다(리뷰 V3). 이전 빌드는 구조안 행의 해시를 풀지 않는다.
- 장과 축약: "c1:<템플릿>|<장 정의>|<구성 계획과 보고 정보>". 이전 빌드는 이 값을 정확히 세 조각으로 풀므로
  표지를 첫 조각에 넣는다. 앞에 붙이면 같은 원장을 읽는 이전 빌드의 작업 목록이 500이었다(재리뷰 RR11).
  이전 빌드는 템플릿이 다르다고 보고 template_changed로 판정한다.
"""

import hashlib
import json

from slidecaptain.models.deck import Deck
from slidecaptain.models.report_purpose import PURPOSE_DEFAULTS, purpose_prompt_values

STRUCTURE_MARKER = "s1:"
CHAPTER_MARKER = "c1:"


def _digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prompt_meta(deck: Deck) -> dict:
    """지시문이 덱 메타에서 읽는 값. 보고자, 미리보기 설정, 유형 확인 표시, 숨은 입력은 들지 않는다."""
    return {"title": deck.meta.title, "audience": deck.meta.audience, "report_type": deck.meta.report_type,
            "purpose": purpose_prompt_values(deck.meta)}


def structure_relevance(deck: Deck) -> str:
    applied = {"structure": deck.structure.model_dump(mode="json"),
               "slides": [s.model_dump(mode="json") for s in deck.slides]}
    return f"{STRUCTURE_MARKER}{_digest(_prompt_meta(deck))}|{_digest(applied)}"


def structure_parts(value: str | None) -> tuple[str, str] | None:
    """이 빌드가 아는 구조안 해시면 (가, 나). 표지가 없거나 모르면 None(ETag로 판정한다)."""
    if not value or not value.startswith(STRUCTURE_MARKER):
        return None
    parts = value[len(STRUCTURE_MARKER):].split("|")
    return (parts[0], parts[1]) if len(parts) == 2 else None


def chapter_relevance(deck: Deck, chapter_id: str, *, legacy: bool = False) -> str:
    """장 재생성과 축약의 관련 입력. legacy는 표지 없는 옛 행과 비교할 때의 옛 계산식(메타 전체)이다. 새 다섯 칸은
    옛 빌드가 쓴 행에 없었으므로 빼고 계산한다. 그래서 업데이트 뒤 유형을 처음 확인해도 옛 후보가 낡지 않는다
    (재리뷰 RR14)."""
    chapter = next((c for c in deck.structure.chapters if c.id == chapter_id), None)
    plan = deck.structure.story_plan
    plan_dump = plan.model_dump(mode="json") if plan else None
    if legacy:
        meta = deck.meta.model_dump(mode="json")
        for name in PURPOSE_DEFAULTS:
            meta.pop(name, None)
        report = _digest({"plan": plan_dump, "meta": meta})
        template = chapter.template if chapter else ""
    else:
        report = _digest({"plan": plan_dump, "meta": _prompt_meta(deck)})
        template = f"{CHAPTER_MARKER}{chapter.template}" if chapter else ""
    return "|".join([template, _digest(chapter.model_dump(mode="json") if chapter else None), report])


BATCH_MARKER = "b1:"


def batch_relevance(deck: Deck, chapter_ids: list[str]) -> str:
    """묶음 부모 행의 장별 관련 입력 (D3c-5, 계획 4.8): "b1:" 뒤에 장 ID별 "c1:" 값을 담은 JSON. 묶음 장 후보를 적용 라우트로
    반영할 때 판정 기준이 된다. 원장 형식 번호는 그대로이고, 이전 빌드의 조회는 묶음 행의 이 칸을 풀지 않는다."""
    values = {cid: chapter_relevance(deck, cid) for cid in chapter_ids}
    return BATCH_MARKER + json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def batch_parts(value: str | None) -> dict[str, str] | None:
    """이 빌드가 아는 묶음 해시면 장 ID별 관련 입력. 표지가 없는 D3c 이전 묶음 행이나 모르는 값은 None."""
    if not value or not value.startswith(BATCH_MARKER):
        return None
    try:
        parsed = json.loads(value[len(BATCH_MARKER):])
    except ValueError:
        return None
    if not isinstance(parsed, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()):
        return None
    return parsed
