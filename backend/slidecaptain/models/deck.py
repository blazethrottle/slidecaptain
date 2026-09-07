"""deck.json 스키마 (설계서 3.2).

슬라이드에는 템플릿 유형과 슬롯 내용만 있다. 좌표와 글자 크기는 데이터에 없다.
본문 장의 제목 텍스트는 슬롯이 아니라 구조안의 chapter.topic에서 온다 (주제형 제목).
"""

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = 1

TemplateName = Literal[
    "cover", "summary", "bullet_box", "table", "compare2", "divider", "callout", "cards",
]
ReportType = Literal["research", "approval", "strategy"]


class Bullet(BaseModel):
    text: str
    level: Literal[0, 1] = 0


class Card(BaseModel):
    heading: str
    bullets: list[Bullet] = []


class CoverSlots(BaseModel):
    """표지 슬롯. 보고자는 슬롯이 아니라 메타(DeckMeta.presenter)에서 그리고, 피보고자는 문서에 적지 않는다
    (2026-09-01 파일럿 관찰 6: 종전 audience 필드 제거. 옛 deck.json의 audience 키는 읽을 때 무시된다)."""

    template: Literal["cover"] = "cover"
    title: str
    subtitle: str = ""
    date: str = ""


class SummarySlots(BaseModel):
    template: Literal["summary"] = "summary"
    conclusion: str
    points: list[Bullet] = []


class BulletBoxSlots(BaseModel):
    template: Literal["bullet_box"] = "bullet_box"
    bullets: list[Bullet] = []
    conclusion: str
    footnote: str = ""


class TableSlots(BaseModel):
    template: Literal["table"] = "table"
    columns: list[str] = Field(min_length=1)
    rows: list[list[str]]
    footnote: str = ""

    @model_validator(mode="after")
    def rows_match_columns(self) -> "TableSlots":
        for i, row in enumerate(self.rows):
            if len(row) != len(self.columns):
                raise ValueError(f"{i}번째 행의 칸 수({len(row)})가 열 수({len(self.columns)})와 다릅니다")
        return self

    @model_validator(mode="after")
    def _cells_single_line(self) -> "TableSlots":
        # 표 셀 줄바꿈은 행 높이 계산과 균일성 규칙을 깨므로 데이터에서 금지한다 (단계 3 결정 8)
        for text in self.columns + [cell for row in self.rows for cell in row]:
            if "\n" in text or "\r" in text:
                raise ValueError("표 칸에는 줄바꿈을 넣을 수 없습니다. 내용을 한 줄로 줄이거나 행을 나눠 주세요")
        return self


class CompareSlots(BaseModel):
    template: Literal["compare2"] = "compare2"
    left: Card
    right: Card
    conclusion: str


class DividerSlots(BaseModel):
    template: Literal["divider"] = "divider"
    section_no: str = ""
    section_title: str


class CalloutSlots(BaseModel):
    """강조 밴드: 전폭 둥근 사각형에 문장 1~3줄 (2026-09-07 DB-1, 벤치마크 원형 2, 슬라이드 절반에서 관측).

    tone은 프리셋 색을 직접 받지 않고 채움 가능한 역할 이름만 받는다: 프리셋이 바뀌면 색이
    따라 바뀌게 하기 위해서다. rule은 테두리 전용 역할이라(DA-3: 벤치마크 테두리 42건 최다,
    채움 0건) 여기서 뺐다.
    """

    template: Literal["callout"] = "callout"
    text: str
    tone: Literal[
        "ink", "ink_soft", "accent1", "accent2", "danger", "ok",
        "surface1", "surface2", "surface3", "surface_danger",
    ] = "surface1"


class CardItem(BaseModel):
    """카드 하나 (2026-09-07 DB-2). badge와 tail은 선택이라 없으면 그 자리를 차지하지 않는다
    (eyebrow/subtitle과 같은 규칙). 본문을 list[Bullet]로 두는 이유는 templateSwitch가 다른
    템플릿의 불릿을 이 자리로 옮길 수 있게 하기 위해서다.
    """

    badge: str = ""
    heading: str
    bullets: list[Bullet] = []
    tail: str = ""
    emphasis: bool = False


class CardsSlots(BaseModel):
    """카드 2~4개를 가로로 나열한다 (2026-09-07 DB-2). compare2와 달리 결론 상자가 없다:
    compare2는 두 옵션을 비교해 하나의 결론으로 수렴하지만, cards는 항목을 나란히 소개하거나
    병렬 비교하는 용도라 공통 결론이 필수가 아니다.
    """

    template: Literal["cards"] = "cards"
    cards: list[CardItem] = Field(min_length=2, max_length=4)


Slots = Annotated[
    Union[
        CoverSlots, SummarySlots, BulletBoxSlots, TableSlots, CompareSlots, DividerSlots,
        CalloutSlots, CardsSlots,
    ],
    Field(discriminator="template"),
]


class Chapter(BaseModel):
    id: str
    topic: str
    conclusion: str = ""
    template: TemplateName
    source_refs: list[str] = []


class Structure(BaseModel):
    chapters: list[Chapter] = []


class Slide(BaseModel):
    chapter_id: str
    # 제목 위 분류 라벨과 제목 아래 한 문장 (2026-09-07 DA-4). 값이 없으면 자리를 차지하지 않는다.
    # 각주는 슬롯 레벨에 이미 있어 여기 두지 않는다: 두 곳에 같은 개념이 생기고 통합은
    # 다르게 해석되는 변경이라 스키마 버전 상향이 필요해진다 (적대 리뷰 확인)
    eyebrow: str = ""
    subtitle: str = ""
    slots: Slots


class DeckMeta(BaseModel):
    title: str
    report_type: ReportType = "research"
    audience: str = ""  # 피보고자: 문체와 상세 수준의 기준으로만 쓰고 문서에 적지 않는다 (2026-09-01)
    presenter: str = ""  # 보고자(이름 또는 부서): 표지에 표기. 장 제목처럼 슬롯이 아니라 여기서 렌더한다 (2026-09-01 추가)
    preset_overrides: dict[str, Any] = {}


class Deck(BaseModel):
    schema_version: int = SCHEMA_VERSION
    meta: DeckMeta
    structure: Structure = Structure()
    slides: list[Slide] = []

    @model_validator(mode="after")
    def _schema_version_supported(self) -> "Deck":
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"이 덱 파일의 스키마 버전({self.schema_version})은 지원하지 않습니다. "
                f"이 앱은 버전 {SCHEMA_VERSION}만 읽을 수 있습니다. "
                f"파일이 더 새 버전이라면 앱을 업데이트해 주세요."
            )
        return self

    @model_validator(mode="after")
    def _chapters_and_slides_consistent(self) -> "Deck":
        seen_ids: set[str] = set()
        for ch in self.structure.chapters:
            if ch.id in seen_ids:
                raise ValueError(f"장 id가 중복되었습니다: {ch.id}")
            seen_ids.add(ch.id)
        chapters_by_id = {ch.id: ch for ch in self.structure.chapters}
        seen_slide_chapters: set[str] = set()
        for slide in self.slides:
            if slide.chapter_id in seen_slide_chapters:
                raise ValueError(
                    f"한 장에 슬라이드가 두 개 있습니다: {slide.chapter_id}. "
                    "장 하나에는 슬라이드 하나만 둘 수 있습니다"
                )
            seen_slide_chapters.add(slide.chapter_id)
            chapter = chapters_by_id.get(slide.chapter_id)
            if chapter is None:
                raise ValueError(
                    f"슬라이드가 구조안에 없는 장을 가리킵니다: {slide.chapter_id}. "
                    "구조안에 장을 먼저 추가하거나 슬라이드를 지워 주세요"
                )
            if chapter.template != slide.slots.template:
                raise ValueError(
                    f"장 {chapter.id}의 template({chapter.template})이 "
                    f"슬롯 template({slide.slots.template})과 다릅니다"
                )
        return self
