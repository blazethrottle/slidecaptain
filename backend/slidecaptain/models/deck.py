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
    columns: list[str]
    rows: list[list[str]]
    footnote: str = ""

    @model_validator(mode="after")
    def rows_match_columns(self) -> "TableSlots":
        for i, row in enumerate(self.rows):
            if len(row) != len(self.columns):
                raise ValueError(f"{i}번째 행의 칸 수({len(row)})가 열 수({len(self.columns)})와 다릅니다")
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
