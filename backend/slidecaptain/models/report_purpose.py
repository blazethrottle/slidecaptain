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
