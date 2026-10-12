"""보고 목적별 구성 참고. 생성 단계의 편집·보존 계약을 대체하지 않는다."""
from slidecaptain.models.story import ReportType


REPORT_TYPE_GUIDES: dict[ReportType, str] = {
    "research": "리서치 결과 보고(연구분석형): 조사 질문과 범위, 조사 방법, 주요 발견, 근거와 한계, 시사점과 출처",
    "approval": "승인요청형: 핵심 요약과 요청사항, 배경과 문제, 대안 비교와 추천, 실행 계획과 리스크",
    "strategy": "전략기획형: 핵심 결론, 현황, 문제와 변화, 전략 방향과 근거, 실행 로드맵",
    "weekly": "주간 업무 보고: 보고 기간, 이번 주 실적, 계획 대비 차이, 장애와 지원 요청, 다음 주 계획",
    "business": "일반 업무 보고: 업무 목적, 업무 현황, 수행 내용, 주요 이슈, 후속 행동",
    "monthly": "월간 보고: 대상 월, 목표와 실적, 전월 및 계획 대비 변화, 원인과 해석 한계, 다음 달 계획",
    "data": "데이터 설명 보고: 설명할 질문, 데이터 범위와 지표 정의, 단위와 기간 및 분모, 관측 결과, 해석과 한계",
    "project": "프로젝트 보고: 목표와 범위, 마일스톤과 진척, 일정과 자원, 리스크와 필요한 결정, 다음 단계",
    "results": "결과 보고: 당초 목표와 평가 기준, 수행 내용과 산출물, 달성 여부, 차이 원인, 교훈과 후속 조치",
    "ir": "IR Pitch Deck: 문제, 해결책과 제품, 시장, 사업 모델, 성과, 성장 전략, 팀, 투자 요청과 자금 사용과 마일스톤",
}

REPORT_TYPE_RULES = (
    "보고 유형의 항목은 자료에 맞게 선택한다. 없는 기간, 담당자, 목표, 실적이나 원인을 지어내지 않는다. "
    "비교할 근거가 없으면 미확인으로 남긴다. 정기 업무 및 설명 보고에 불필요한 승인 요청이나 전략 제안을 강요하지 않는다."
)


# 원하는 결과의 화면 이름 (제품 설계 6절). 보고 유형과는 다른 축이다
OUTCOME_LABELS = {
    "facts": "사실 및 데이터 중심 보고서",
    "business_plan": "사업 기획안",
    "persuasion": "투자자 및 의사결정자 설득",
    "other": "기타",
}
NOT_ENTERED = "미입력(사용자가 정하지 않음)"
# 보고 목적 값의 생성 규칙 (D3b-3, 계획 4.4). 원하는 결과는 사용자가 명시한 목적이라 유형 규칙의 "강요하지
# 않는다"보다 우선한다(리뷰 V14). 미입력 값을 지어내지 않는 것은 지금 유형 규칙과 같다
PURPOSE_RULES = (
    "미입력은 사용자가 정하지 않았다는 뜻이다. 미입력인 기간, 성과, 담당, 목표를 만들지 않는다. "
    "원하는 결과는 사용자가 명시한 목적이므로 유형 규칙의 '강요하지 않는다'보다 우선한다. 단 근거 없는 제안을 만들지 않는다."
)


def purpose_block(meta) -> str:
    """지시문에 넣는 보고 목적 줄. 값은 purpose_prompt_values에서 꺼내므로 판정 해시, 구성 계획 지문과 항상 같은
    칸을 본다(재리뷰 RR12). 숨은 입력은 넣지 않는다."""
    from slidecaptain.models.report_purpose import REPORT_DETAIL_FIELDS, purpose_prompt_values

    values = purpose_prompt_values(meta)
    outcome = values.get("desired_outcome")
    if outcome is None:
        outcome_text = "사용자 미선택(기본: 사실 및 데이터 중심)"
    elif outcome == "other":
        outcome_text = f"기타: {values['desired_outcome_other']}" if "desired_outcome_other" in values \
            else f"기타(설명 {NOT_ENTERED})"
    else:
        outcome_text = OUTCOME_LABELS[outcome]
    details = values.get("report_details", {})
    lines = [f"- 전달할 핵심 내용: {values.get('key_message', NOT_ENTERED)}", f"- 원하는 결과: {outcome_text}"]
    lines += [f"- {label}: {details.get(name, NOT_ENTERED)}" for name, label in REPORT_DETAIL_FIELDS.get(meta.report_type, ())]
    return "\n".join(lines) + "\n" + PURPOSE_RULES
