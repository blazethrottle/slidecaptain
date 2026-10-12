"""보고 목적 항목과 형식 등급 (개정판 D3b-1, 계획 4.2).

새 항목(유형 확인 표시, 핵심 내용, 원하는 결과와 기타 설명, 유형별 추가 입력)은 덱 메타에만 둔다.
형식 등급은 "어느 앱이 이 덱을 읽는가"다. 1은 0.2.0, 2는 개정판 중간 빌드(D2a~D3a), 3은 D3b 이후만
읽는다. 보고 유형이나 새 항목을 더하면 이 등급표와 manifest 형식 번호를 다시 본다(test_project_format의
스키마 해시 시험이 이 검토를 강제한다).
"""

from typing import Literal

from slidecaptain.models.story import ReportType

DesiredOutcome = Literal["facts", "business_plan", "persuasion", "other"]

# 길이 상한. 핵심 내용과 기타 설명은 재작성과 도식 지시의 기존 상한(instructions 8,000자)을 출발점으로 썼고,
# 추가 입력 한 칸은 제품 설계 5절 B 표의 칸이 기간, 대상, 단계 같은 짧은 값이라 그 8분의 1로 두었다.
# 측정 근거가 아니므로 D6 사용성 검증에서 실제 입력 길이를 기록해 다시 정한다 (계획 8절 가정 5)
KEY_MESSAGE_MAX = 8_000
OUTCOME_OTHER_MAX = 8_000
DETAIL_MAX = 1_000

# 유형별 추가 입력 칸: 제품 설계 5절 B 표의 "추가로 받는 정보". 저장 키는 "유형.칸"이다.
# IR의 "독자"는 보고 정보의 피보고자와 같으므로 칸을 따로 두지 않는다
REPORT_DETAIL_FIELDS: dict[ReportType, tuple[tuple[str, str], ...]] = {
    "weekly": (("period", "보고 기간"), ("baseline", "계획 또는 이전 보고서")),
    "business": (("target_work", "대상 업무"), ("share_purpose", "공유 목적")),
    "monthly": (("month", "대상 월"), ("comparison_basis", "목표 또는 비교 기준")),
    "data": (("metrics", "주요 지표"), ("scope", "기간과 대상")),
    "research": (("question", "조사 질문"), ("scope", "조사 범위")),
    "project": (("project", "프로젝트"), ("reference_date", "기준일"), ("milestones", "주요 마일스톤")),
    "results": (("activity_scope", "활동 범위"), ("goal_criteria", "목표와 평가 기준")),
    "approval": (("decision_question", "결정할 질문"), ("alternatives", "대안")),
    "strategy": (("goal", "목표"), ("review_period", "검토 기간")),
    "ir": (("investment_stage", "투자 단계"), ("ask_and_use", "투자 요청과 사용 계획")),
}
DETAIL_KEYS = frozenset(f"{t}.{name}" for t, fields in REPORT_DETAIL_FIELDS.items() for name, _ in fields)

# 0.2.0(v0.2.0)이 아는 보고 유형과 개정판 중간 빌드(D2a~D3a)가 아는 보고 유형
LEGACY_REPORT_TYPES = frozenset({"research", "approval", "strategy"})
INTERIM_REPORT_TYPES = LEGACY_REPORT_TYPES | {"weekly", "business", "monthly", "data", "project", "results"}

# 새 항목의 이름과 기본값. 기본값이면 직렬화에서 뺀다(기존 덱의 바이트, ETag, 지문을 바꾸지 않는다)
PURPOSE_DEFAULTS: dict[str, object] = {
    "report_type_confirmed": False,
    "key_message": "",
    "desired_outcome": None,
    "desired_outcome_other": "",
    "report_details": {},
}


def is_blank(value: str | None) -> bool:
    """비어 있음의 판정. 등급, 진행 사유, 지시문의 "미입력", 숨은 입력 개수가 모두 이 함수를 쓴다."""
    return value is None or not value.strip()


def has_purpose_content(meta) -> bool:
    """사용자가 입력한 새 내용 항목이 있는가. 유형 확인 표시는 세지 않는다(계획 4.1의 Q1 해석).
    숨은 입력(지금 유형이 아닌 유형의 추가 입력, 기타가 아닐 때의 기타 설명)도 데이터라 센다."""
    return (
        not is_blank(meta.key_message)
        or meta.desired_outcome is not None
        or not is_blank(meta.desired_outcome_other)
        or any(not is_blank(v) for v in meta.report_details.values())
    )


def level_of(report_types: list[object], purpose_content: bool) -> int:
    """형식 등급. 보고 유형 값들(메타와 구성 계획)과 새 내용 항목의 유무로 정한다."""
    if purpose_content or any(t not in INTERIM_REPORT_TYPES for t in report_types):
        return 3
    if any(t not in LEGACY_REPORT_TYPES for t in report_types):
        return 2
    return 1


def deck_level(deck) -> int:
    values: list[object] = [deck.meta.report_type]
    if deck.structure.story_plan is not None:
        values.append(deck.structure.story_plan.brief.report_type)
    return level_of(values, has_purpose_content(deck.meta))


def purpose_prompt_values(meta) -> dict:
    """지시문이 읽는 보고 목적 값 (D3b-2, 재리뷰 RR12). 지시문 네 곳, 구조안 판정 (가), 장 관련 입력,
    구성 계획 지문이 모두 이 결과를 쓴다. 숨은 입력은 들지 않으므로 숨은 입력을 지워도 계획과 후보가 낡지 않는다.
    기본값이면 빈 사전이라 기존 지문이 그대로다. 값은 앞뒤 공백을 지운다. 자동 저장이 입력 중의 끝 공백이나
    줄바꿈을 저장해도 같은 내용이면 계획과 후보가 낡지 않는다(α 묶음 리뷰 A5). 저장값은 입력 그대로다."""
    values: dict = {}
    if not is_blank(meta.key_message):
        values["key_message"] = meta.key_message.strip()
    if meta.desired_outcome is not None:  # None(사용자 미선택)과 명시 선택을 구별한다
        values["desired_outcome"] = meta.desired_outcome
        if meta.desired_outcome == "other" and not is_blank(meta.desired_outcome_other):
            values["desired_outcome_other"] = meta.desired_outcome_other.strip()
    details = {
        name: meta.report_details[f"{meta.report_type}.{name}"].strip()
        for name, _ in REPORT_DETAIL_FIELDS.get(meta.report_type, ())
        if not is_blank(meta.report_details.get(f"{meta.report_type}.{name}"))
    }
    if details:
        values["report_details"] = details
    return values


def purpose_texts(meta) -> list[str]:
    """보고 목적 값의 문자열 목록. 사용자가 직접 적은 보고 정보이므로 미검증 수치 검사의 허용 목록에 더한다
    (D3b-3 리뷰 R2). 지시문과 같은 칸만 담도록 purpose_prompt_values에서 꺼낸다."""
    values = purpose_prompt_values(meta)
    texts = [values[name] for name in ("key_message", "desired_outcome_other") if name in values]
    return texts + list(values.get("report_details", {}).values())


def prompt_dump(deck) -> dict:
    """AI 지시문의 문맥에 넣는 덱 덤프 (D3b-3 리뷰 R1, R11). 재작성 문맥과 수리의 독립 검수가 쓴다.

    보고 목적 다섯 칸은 지시 부분(purpose_block)에 한 번만 넣으므로 여기서 뺀다. 숨은 입력이 외부 AI로
    나가지 않게 하는 것도 이 함수의 몫이다. 출력 지문용 output_dump와 용도가 달라 따로 둔다."""
    raw = deck.model_dump(mode="json")
    for name in PURPOSE_DEFAULTS:
        raw["meta"].pop(name, None)
    return raw


def output_dump(deck) -> dict:
    """출력 지문(내보내기, 수치 검토, 의미 검토)에 넣는 덱 덤프 (D3b-2, 재리뷰 RR4).

    보고 목적 다섯 칸은 PPTX에 나오지 않는 생성 입력이라 뺀다. schema_version은 보고 목적 값으로 정해지므로
    1로 고정한다(빼면 기존 덱의 지문이 바뀐다). 기존 덱의 덤프는 그대로다.
    출력 지문은 검수 기록의 기준 비교에만 쓴다. 지문이 같아도 수치 검토와 의미 검토는 구성 계획의 낡음을
    따로 보므로, 이 지문을 검토 결과의 캐시 열쇠로 쓰지 않는다(D3b-2 리뷰 R6). 지시문 문맥에는 prompt_dump를 쓴다."""
    raw = deck.model_dump(mode="json")
    raw["schema_version"] = 1
    for name in PURPOSE_DEFAULTS:
        raw["meta"].pop(name, None)
    return raw
