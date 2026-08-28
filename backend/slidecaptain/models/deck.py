"""deck.json 스키마 (설계서 3.2).

슬라이드에는 템플릿 유형과 슬롯 내용만 있다. 좌표와 글자 크기는 데이터에 없다.
본문 장의 제목 텍스트는 슬롯이 아니라 구조안의 chapter.topic에서 온다 (주제형 제목).
"""

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = 1

TemplateName = Literal["cover", "summary", "bullet_box", "table", "compare2", "divider"]
ReportType = Literal["research", "approval", "strategy"]


class Bullet(BaseModel):
    text: str
    level: Literal[0, 1] = 0


class Card(BaseModel):
    heading: str
    bullets: list[Bullet] = []


class CoverSlots(BaseModel):
    template: Literal["cover"] = "cover"
    title: str
    subtitle: str = ""
    date: str = ""
    audience: str = ""


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


Slots = Annotated[
    Union[CoverSlots, SummarySlots, BulletBoxSlots, TableSlots, CompareSlots, DividerSlots],
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
    slots: Slots


class DeckMeta(BaseModel):
    title: str
    report_type: ReportType = "research"
    audience: str = ""
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
