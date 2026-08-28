"""프롬프트 조립 (설계서 4.1). 호출 2종: 구조안 생성, 장별 내용 생성.

프롬프트는 프로바이더와 무관한 공통부다: 어느 프로바이더로 호출해도 같은
지시가 나가야 산출물 품질이 일관된다 (설계서 1.1의 목적 2).
"""

from slidecaptain.models.deck import (
    BulletBoxSlots,
    Chapter,
    CompareSlots,
    CoverSlots,
    Deck,
    DeckMeta,
    DividerSlots,
    SummarySlots,
    TableSlots,
)
from slidecaptain.models.render import CapacityWarning

REPORT_TYPE_GUIDES: dict[str, str] = {
    "research": "연구분석형: 목표와 배경, 결과 요약, 결과 상세, 반드시 필요한 사항, 출처 순서로 장을 구성한다",
    "approval": "승인요청형: 핵심 요약과 요청사항, 배경과 문제, 대안 비교와 추천, 실행 계획과 리스크 순서로 장을 구성한다",
    "strategy": "전략기획형: 핵심 결론, 현황, 문제와 변화, 전략 방향과 근거, 실행 로드맵 순서로 장을 구성한다",
}

TEMPLATE_GUIDE = """\
사용할 수 있는 템플릿:
- cover: 표지 (제목, 부제, 날짜, 보고 대상). 첫 장에 쓴다
- summary: 핵심 요약 (결론 강조 박스 + 요점 목록)
- bullet_box: 가장 흔한 본문 장 (불릿 + 결론 박스 + 선택 각주)
- table: 비교표, 데이터 표 (열 이름 + 행 + 선택 각주)
- compare2: 옵션 비교나 전후 대비 카드 2개 + 결론 박스
- divider: 섹션 구분 간지"""

STYLE_RULES = """\
문체 규칙:
- 장 제목(topic)은 주제형으로 짧게 쓴다: 그 장이 무엇을 말하는지. 결론 문장은 conclusion에 둔다
- 본문, 불릿, 표 칸은 압축 문체를 쓴다: 명사형 종결, 조사 생략 허용
- 엠대시(U+2014)와 중점(U+00B7)은 쓰지 않는다
- 자료에 없는 수치를 만들지 않는다. 모든 숫자는 자료 원문에 있는 값만 쓴다"""

_SLOTS_BY_TEMPLATE = {
    "cover": CoverSlots,
    "summary": SummarySlots,
    "bullet_box": BulletBoxSlots,
    "table": TableSlots,
    "compare2": CompareSlots,
    "divider": DividerSlots,
}

_CONTRACT_LABELS = {
    "points_max_lines": "요점 목록 전체",
    "bullets_max_lines": "불릿 전체",
    "conclusion_max_lines": "결론 박스",
    "footnote_max_lines": "각주",
    "rows_max_single_line": "표 행 수 (머리글 포함, 한 줄짜리 행 기준)",
    "card_heading_max_lines": "카드 소제목",
    "card_bullets_max_lines": "카드 하나의 불릿 전체",
}


def _sources_block(sources: dict[str, str]) -> str:
    return "\n\n".join(f"=== 자료: {name} ===\n{text}" for name, text in sources.items())


def build_structure_prompt(
    meta: DeckMeta,
    sources: dict[str, str],
    target_chapters: int | None = None,
    instructions: str = "",
) -> str:
    count_line = (
        f"- 목표 장수: {target_chapters}장 내외 (표지와 간지 포함)"
        if target_chapters
        else "- 목표 장수: 자료 분량에 맞게 정한다 (표지와 간지 포함)"
    )
    extra = f"\n추가 지시:\n{instructions}\n" if instructions else ""
    return f"""당신은 보고 슬라이드의 구조를 설계한다. 아래 자료를 읽고 장 구성안을 만들어라.

보고 정보:
- 제목: {meta.title}
- 보고 유형: {REPORT_TYPE_GUIDES[meta.report_type]}
- 피보고자: {meta.audience or "미지정"}
{count_line}

{TEMPLATE_GUIDE}

{STYLE_RULES}

각 장은 topic(주제형 제목), conclusion(그 장의 결론 한 줄), template(템플릿 이름),
source_refs(그 장의 근거가 되는 자료 파일 이름 목록. 아래 자료의 파일 이름만 쓸 것)를 갖는다.
{extra}
{_sources_block(sources)}"""


def structure_response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "chapters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "conclusion": {"type": "string"},
                        "template": {
                            "type": "string",
                            "enum": ["cover", "summary", "bullet_box", "table", "compare2", "divider"],
                        },
                        "source_refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["topic", "conclusion", "template", "source_refs"],
                },
            }
        },
        "required": ["chapters"],
    }


def _contract_block(contract: dict[str, int], chars_per_line: int | None = None) -> str:
    if not contract:
        return "분량 한도: 이 템플릿은 짧은 텍스트만 담는다. 각 칸은 한 줄로 쓴다"
    lines = "\n".join(
        f"- {_CONTRACT_LABELS.get(key, key)}: 최대 {value}줄" for key, value in contract.items()
    )
    hint = (
        f"\n- 환산 안내: 본문 한 줄은 한글 약 {chars_per_line}자 분량이다 (2단 비교 카드 안에서는 그 절반)"
        if chars_per_line
        else ""
    )
    return "분량 한도 (실제 폰트 폭으로 실측한 줄수 기준. 초과하면 재생성을 요구한다):\n" + lines + hint


def build_chapter_prompt(
    deck: Deck,
    chapter: Chapter,
    sources: dict[str, str],
    contract: dict[str, int],
    today: str,
    instructions: str = "",
    chars_per_line: int | None = None,
) -> str:
    structure_lines = "\n".join(
        f"- [{ch.id}] {ch.topic} ({ch.template}): {ch.conclusion}"
        for ch in deck.structure.chapters
    )
    extra = f"\n추가 지시:\n{instructions}\n" if instructions else ""
    # cover와 divider는 자료가 필요 없다: 자료 전문을 넣으면 사용량만 낭비된다 (결정 11)
    sources_part = (
        "" if chapter.template in ("cover", "divider") else "\n" + _sources_block(sources)
    )
    return f"""당신은 보고 슬라이드 한 장의 내용을 채운다.

보고 정보:
- 덱 제목: {deck.meta.title}
- 피보고자: {deck.meta.audience or "미지정"}
- 오늘 날짜: {today}

덱 전체 구조 (맥락으로만 참고):
{structure_lines}

채울 장: [{chapter.id}] {chapter.topic}
- 이 장의 결론: {chapter.conclusion or "미정 (자료에서 도출)"}
- 템플릿: {chapter.template}

{_contract_block(contract, chars_per_line)}

{STYLE_RULES}
{extra}{sources_part}"""


def chapter_response_schema(template: str) -> dict:
    return _SLOTS_BY_TEMPLATE[template].model_json_schema()


def build_format_retry_prompt(base_prompt: str, raw_text: str) -> str:
    # 매 호출이 새 세션이라 직전 응답이 모델 컨텍스트에 없다: 실패 원문을 동봉한다 (결정 12)
    return (
        base_prompt
        + "\n\n직전 시도의 응답이 요구한 JSON 형식에 맞지 않았다. 실패한 응답은 다음과 같다:\n"
        + raw_text[:2000]
        + "\n\n스키마를 정확히 지켜 처음부터 다시 생성하라."
    )


def build_condense_prompt(
    base_prompt: str, warnings: list[CapacityWarning], draft_json: str
) -> str:
    if warnings:
        listed = "\n".join(f"- {w.slot}: {w.message}" for w in warnings)
        ask = "이 초안이 분량 한도를 초과했다. 요지를 유지하면서 다음 항목을 한도 안으로 축약해 다시 생성하라:\n" + listed
    else:
        # 수동 축약(결정 13): 초과가 아니어도 더 간결한 버전을 요청할 수 있다
        ask = "이 초안을 요지를 유지하면서 더 간결하게 축약해 다시 생성하라."
    return base_prompt + "\n\n직전에 생성된 초안은 다음과 같다:\n" + draft_json + "\n\n" + ask
