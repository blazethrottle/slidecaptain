"""프롬프트 조립 (설계서 4.1). 호출 2종: 구조안 생성, 장별 내용 생성.

프롬프트는 프로바이더와 무관한 공통부다: 어느 프로바이더로 호출해도 같은
지시가 나가야 산출물 품질이 일관된다 (설계서 1.1의 목적 2).
"""

from slidecaptain.models.deck import (
    BulletBoxSlots,
    CalloutSlots,
    CardsSlots,
    Chapter,
    CompareSlots,
    CoverSlots,
    Deck,
    DeckMeta,
    DividerSlots,
    MatrixSlots,
    ProcessSlots,
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
사용할 수 있는 템플릿 (아래에서 내용에 맞는 조건을 고른다. 어느 조건에도 맞지 않으면 목록 맨 마지막 bullet_box를 쓴다):
- cover: 덱의 첫 장일 때 쓴다 (제목, 부제, 날짜. 보고자는 앱이 별도로 채우므로 적지 않는다)
- divider: 섹션을 나눌 때 쓴다 (구분 간지 한 장)
- summary: 핵심 결론 하나와 요점 목록으로 정리되는 내용일 때 쓴다 (결론 강조 박스 + 요점 목록)
- table: 여러 항목을 같은 기준의 열로 비교하는 데이터일 때 쓴다 (열 이름 + 행 + 선택 각주)
- compare2: 옵션 두 개나 전후를 나란히 대비하는 내용일 때 쓴다 (카드 2개 + 결론 박스)
- callout: 전폭 강조 밴드. 짧은 핵심 문장 하나만 크게 강조할 때 쓴다 (1~3줄)
- cards: 카드 2~4개로 항목을 나란히 비교하거나 소개할 때 쓴다 (배지와 꼬리 라벨은 선택)
- process: 순서 있는 절차나 단계를 번호로 나열할 때 쓴다 (단계 3~6개, 부제와 보조 라벨 2개는 선택)
- matrix: 분류 기준으로 항목을 대조할 때 쓴다 (행 3~6개, 왼쪽 분류/가운데 대표 항목/오른쪽 나열, 대표 항목과 나열은 선택)
- bullet_box: 위 조건 중 어디에도 맞지 않는 일반 본문일 때 쓴다 (불릿 + 결론 박스 + 선택 각주)"""

STYLE_RULES = """\
문체 규칙:
- 장 제목(topic)은 주제형으로 짧게 쓴다: 그 장이 무엇을 말하는지. 결론 문장은 conclusion에 둔다
- 본문, 불릿, 표 칸은 압축 문체를 쓴다: 명사형 종결, 조사 생략 허용
- 엠대시(U+2014)와 중점(U+00B7)은 쓰지 않는다
- 자료에 없는 수치를 만들지 않는다. 모든 숫자는 자료 원문에 있는 값만 쓴다
- 피보고자는 문체와 상세 수준을 맞추는 기준으로만 쓴다. 보고 정보의 피보고자 항목 값을 표지, 제목, 호칭, 인사말에 옮겨 적지 않는다.
  요청사항은 "승인 요청"처럼 대상을 호칭하지 않고 쓴다"""

_SLOTS_BY_TEMPLATE = {
    "cover": CoverSlots,
    "summary": SummarySlots,
    "bullet_box": BulletBoxSlots,
    "table": TableSlots,
    "compare2": CompareSlots,
    "divider": DividerSlots,
    "callout": CalloutSlots,
    "cards": CardsSlots,
    "process": ProcessSlots,
    "matrix": MatrixSlots,
}

_CONTRACT_LABELS = {
    "cover_title_max_lines": "표지 제목",
    "subtitle_max_lines": "부제",
    "date_max_lines": "날짜",
    "section_no_max_lines": "섹션 번호",
    "section_title_max_lines": "섹션 제목",
    "points_max_lines": "요점 목록 전체",
    "bullets_max_lines": "불릿 전체",
    "conclusion_max_lines": "결론 박스",
    "footnote_max_lines": "각주",
    "rows_max_single_line": "표 행 수 (머리글 포함, 한 줄짜리 행 기준)",
    "card_heading_max_lines": "카드 소제목",
    "card_bullets_max_lines": "카드 하나의 불릿 전체",
    "text_max_lines": "강조 문장",
    "card_badge_max_lines": "카드 배지",
    "card_tail_max_lines": "카드 꼬리 라벨",
    "step_heading_max_lines": "단계 제목",
    "step_subtitle_max_lines": "단계 부제",
    "step_label_max_lines": "단계 보조 라벨",
    "row_category_max_lines": "분류 셀",
    "row_primary_max_lines": "대표 항목",
    "row_items_max_lines": "나열 항목",
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
                            "enum": [
                                "cover", "summary", "bullet_box", "table", "compare2", "divider",
                                "callout", "cards", "process", "matrix",
                            ],
                        },
                        "source_refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["topic", "conclusion", "template", "source_refs"],
                },
            }
        },
        "required": ["chapters"],
    }


# 줄 수 한도가 "한 줄짜리 항목 개수 기준 하한" 으로 정의된 키 (capacity.items_that_fit). AI 가 줄 수와 항목 수를
# 같은 것으로 읽게 문구에 개수를 함께 적는다 (2026-09-02 Critical 묶음 태스크 A)
_ITEM_COUNT_KEYS = {
    "points_max_lines", "bullets_max_lines", "card_bullets_max_lines", "row_items_max_lines",
}

# 새 템플릿 4종의 슬롯 의미 한 줄 안내 (2026-09-07 DB-5). 기존 6종은 필드 이름만으로 뜻이
# 분명해(bullets, conclusion, columns/rows 등) 안내가 필요 없었다. 새 템플릿은 이름만으로
# 용도가 갈리지 않는 필드가 있다: cards의 badge/tail/emphasis, process의 notes, matrix의
# category/primary/items, callout의 tone(색 역할 이름). 계약 블록은 이미 그 장의 템플릿
# 하나로 좁혀져 있어(실측: 계약 블록 136자 / 전체 1,243자) 분량 부담 없이 여기 추가한다.
_SLOT_NOTES: dict[str, str] = {
    "callout": (
        "tone은 문장의 성격에 맞는 색 역할을 고른다: danger는 위험이나 우려, ok는 긍정이나 달성, "
        "accent1과 accent2는 일반 강조, 나머지(ink 계열과 surface 계열)는 중립 배경이다"
    ),
    "cards": (
        "badge는 카드 위쪽 짧은 라벨, tail은 카드 아래쪽 짧은 라벨이다(둘 다 선택, 없으면 비운다). "
        "emphasis를 true로 하면 그 카드만 어두운 채움과 강조 테두리로 도드라진다: 추천안이나 "
        "핵심 카드 하나에만 true를 쓰고 나머지는 false로 둔다"
    ),
    "process": (
        "notes는 단계 오른쪽에 붙는 보조 라벨 목록이다(선택, 최대 2개): 기간이나 담당처럼 짧은 "
        "부가 정보만 담는다. 단계 번호는 데이터에 넣지 않는다: 순서대로 자동으로 매겨진다"
    ),
    "matrix": (
        "category는 그 행의 분류축 이름(필수)이다. primary는 그 분류의 대표 항목 한 줄(선택), "
        "items는 그 분류에 속하는 항목 나열(선택)이다: 대표 항목이나 나열 중 없는 쪽은 비운다"
    ),
}


def _slot_notes_block(template: str) -> str:
    """새 템플릿 4종의 슬롯 안내 한 줄. 해당 없는 템플릿은 빈 문자열이라 프롬프트가 바뀌지 않는다."""
    note = _SLOT_NOTES.get(template)
    return f"슬롯 안내: {note}\n\n" if note else ""


def _contract_block(template: str, contract: dict[str, int], char_hints: dict[str, int] | None = None) -> str:
    if not contract:
        # 모든 템플릿이 계약을 가지므로(표지와 간지도 2026-09-02 부터) 서비스 경로에서는 도달하지 않는다.
        # 계약 없이 호출하는 테스트와 외부 호출자를 위한 폴백으로만 남긴다 (구현 리뷰 R3)
        return "분량 한도: 이 템플릿은 짧은 텍스트만 담는다. 각 칸은 한 줄로 쓴다"
    lines = []
    if template == "cards":
        # 개수 제약은 max_lines 형태의 계약 딕셔너리에 담을 수 없는 값이라 여기서 별도로 넣는다
        # (2026-09-07 DB-2). AI가 실제로 만드는 cards 배열 길이(2~4)를 직접 겨냥한 문구다.
        lines.append("- 카드 개수: 2개 이상 4개 이하")
    if template == "process":
        # cards와 같은 이유: steps 배열 길이(3~6)는 max_lines 계약에 담기지 않는다 (2026-09-07 DB-3)
        lines.append("- 단계 개수: 3개 이상 6개 이하")
    if template == "matrix":
        # cards/process와 같은 이유: rows 배열 길이(3~6)는 max_lines 계약에 담기지 않는다 (2026-09-07 DB-4)
        lines.append("- 행 개수: 3개 이상 6개 이하")
    for key, value in contract.items():
        suffix = f" (한 줄짜리 항목 {value}개 기준)" if key in _ITEM_COUNT_KEYS else ""
        unit = "행" if key == "rows_max_single_line" else "줄"
        lines.append(f"- {_CONTRACT_LABELS.get(key, key)}: 최대 {value}{unit}{suffix}")
    hint = (
        "\n- 환산 안내 (한 줄 분량): " + ", ".join(f"{name} 약 {n}자" for name, n in char_hints.items())
        if char_hints
        else ""
    )
    return "분량 한도 (실제 폰트 폭으로 실측한 줄수 기준. 초과하면 재생성을 요구한다):\n" + "\n".join(lines) + hint


def build_chapter_prompt(
    deck: Deck,
    chapter: Chapter,
    sources: dict[str, str],
    contract: dict[str, int],
    today: str,
    instructions: str = "",
    char_hints: dict[str, int] | None = None,
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

{_slot_notes_block(chapter.template)}{_contract_block(chapter.template, contract, char_hints)}

{STYLE_RULES}
{extra}{sources_part}"""


def chapter_response_schema(template: str) -> dict:
    return _SLOTS_BY_TEMPLATE[template].model_json_schema()


def build_format_retry_prompt(base_prompt: str, raw_text: str, reason: str = "") -> str:
    # 매 호출이 새 세션이라 직전 응답이 모델 컨텍스트에 없다: 실패 원문을 동봉한다 (결정 12)
    # reason은 실패 사유 한 줄이다 (2026-09-07 DB-5): cards/process/matrix처럼 개수 제약이
    # 있는 템플릿은 원문만으로 "무엇이" 규칙을 어겼는지 AI가 스스로 못 짚는 경우가 잦았다.
    # 비어 있으면 이 줄을 아예 넣지 않는다: 사유를 특정하기 애매한 실패도 안전하게 동작해야 한다.
    reason_line = f"\n실패 사유: {reason}" if reason else ""
    return (
        base_prompt
        + "\n\n직전 시도의 응답이 요구한 JSON 형식에 맞지 않았다. 실패한 응답은 다음과 같다:\n"
        + raw_text[:2000]
        + reason_line
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
