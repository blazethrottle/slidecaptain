"""deck.json 스키마 (설계서 3.2).

슬라이드에는 템플릿 유형과 슬롯 내용만 있다. 좌표와 글자 크기는 데이터에 없다.
본문 장의 제목 텍스트는 슬롯이 아니라 구조안의 chapter.topic에서 온다 (주제형 제목).
"""

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from slidecaptain.models.diagram import DiagramInput, parse_diagram_spec
from slidecaptain.models.story import ReportType, StoryPlan
from slidecaptain.models.expression import ChartSpec, TextSpan, validate_spans
from slidecaptain.models.change_review import DocumentChangeReview
from slidecaptain.models.direct_edit import ElementEdit, frame_keys, normalize_edits
from slidecaptain.models.report_purpose import (
    DETAIL_KEYS, DETAIL_MAX, KEY_MESSAGE_MAX, OUTCOME_OTHER_MAX, PURPOSE_DEFAULTS, DesiredOutcome, deck_level,
    is_blank,
)

# 2026-10-08 D2a-1, 2026-10-12 D3b-1, 2026-10-13 D3c-1: 덱 내용 등급(models/report_purpose.py)이 4이면 3, 3이면 2, 아니면 1이다.
# 입력으로 받은 값(1~3)은 무시하고 검증 뒤 내용으로 정한다. 4 이상은 이 앱보다 새 앱이 쓴 덱이라 거절한다.
# 3종 유형에 새 항목만 더한 덱은 0.2.0의 필드 검증을 통과하고 이 버전 검사에서 막힌다(새 항목을 지우지 않게).
# 덱 스키마를 바꾸면 test_project_format의 스키마 해시 시험이 실패하므로 그때 형식 판정을 함께 갱신한다.
SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = (1, 2, 3)

GeneratedTemplateName = Literal[
    "cover", "summary", "bullet_box", "table", "compare2", "divider", "callout", "cards", "process",
    "matrix",
]
TemplateName = Literal[GeneratedTemplateName, "diagram"]


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


class ProcessStep(BaseModel):
    """번호 단계 하나 (2026-09-07 DB-3). 번호는 데이터에 두지 않고 렌더 순서(자동 채번)에서
    나온다: 장 제목이 슬롯이 아니라 구조안 순서(chapter.topic)에서 오는 것과 같은 원칙이다.
    subtitle과 notes는 선택이라 없으면 그 자리를 차지하지 않는다(cards의 badge/tail과 같은 규칙).
    """

    heading: str
    subtitle: str = ""
    notes: list[str] = Field(default=[], max_length=2)


class ProcessSlots(BaseModel):
    """번호 단계 3~6개를 전폭 행으로 쌓는다 (2026-09-07 DB-3). 사용자가 요구한 "플로우차트"의
    실제 형태다. cards와 같은 이유로 결론과 각주에 대응하는 자리가 없다: 단계 나열 자체가
    내용이라 공통 결론이 필수가 아니다.
    """

    template: Literal["process"] = "process"
    steps: list[ProcessStep] = Field(min_length=3, max_length=6)


class MatrixRow(BaseModel):
    """행렬 행 하나 (2026-09-07 DB-4). 왼쪽 분류 셀(category)은 항상 있고, 가운데 대표 항목
    (primary)과 오른쪽 나열(items)은 선택이라 없으면 그 자리를 차지하지 않는다(cards의
    badge/tail과 같은 규칙).

    표(TableSlots)와 다른 점: 표는 열 이름이 있는 균일한 격자이고, matrix는 분류축이 왼쪽에
    고정된 행 나열이라 열 이름이 없고 행마다 가운데/오른쪽 내용의 유무가 달라질 수 있다.
    """

    category: str
    primary: str = ""
    items: list[str] = []


class MatrixSlots(BaseModel):
    """분류 행 3~6개를 전폭 행으로 쌓는다 (2026-09-07 DB-4). process와 같은 이유로 결론과
    각주에 대응하는 자리가 없다: 행 나열 자체가 내용이라 공통 결론이 필수가 아니다.
    """

    template: Literal["matrix"] = "matrix"
    rows: list[MatrixRow] = Field(min_length=3, max_length=6)


class DiagramSlots(BaseModel):
    """도식의 의미 입력만 저장한다. 배치/검수 결과는 계산 출력에만 존재한다."""

    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")

    template: Literal["diagram"] = "diagram"
    diagram: DiagramInput
    footnote: str = ""


GeneratedSlots = Annotated[
    Union[
        CoverSlots, SummarySlots, BulletBoxSlots, TableSlots, CompareSlots, DividerSlots,
        CalloutSlots, CardsSlots, ProcessSlots, MatrixSlots,
    ],
    Field(discriminator="template"),
]
Slots = Annotated[Union[GeneratedSlots, DiagramSlots], Field(discriminator="template")]


class Chapter(BaseModel):
    id: str
    topic: str
    conclusion: str = ""
    template: TemplateName
    source_refs: list[str] = []


class GeneratedChapter(Chapter):
    template: GeneratedTemplateName


class Structure(BaseModel):
    chapters: list[Chapter] = []
    story_plan: StoryPlan | None = None


def _omittable(schema: dict) -> None:
    schema.pop("default", None)


class Slide(BaseModel):
    chapter_id: str
    # 제목 위 분류 라벨과 제목 아래 한 문장 (2026-09-07 DA-4). 값이 없으면 자리를 차지하지 않는다.
    # 각주는 슬롯 레벨에 이미 있어 여기 두지 않는다: 두 곳에 같은 개념이 생기고 통합은
    # 다르게 해석되는 변경이라 형식 상향이 필요해진다 (적대 리뷰 확인. 2026-10-08부터 storage/project_format.py)
    eyebrow: str = ""
    subtitle: str = ""
    slots: Slots
    chart: ChartSpec | None = None
    text_spans: list[TextSpan] = Field(default_factory=list,max_length=100)
    # 직접 수정 (D3c-1, 계획 4.2). 비면 직렬화하지 않아 기존 덱의 바이트와 지문이 그대로다. 열쇠는 frame_keys가 정한다
    direct_edits: dict[str, ElementEdit] = Field(default_factory=dict, json_schema_extra=_omittable)

    # 생략 규칙은 이 함수 하나에 둔다. 직렬화 함수를 하나 더 두면 pydantic이 마지막 것만 써서 위 생략이 조용히
    # 꺼진다 (D3c 계획 리뷰 저장 S5)
    @model_serializer(mode='wrap')
    def expression_serialization(self,handler):
        result=handler(self)
        if self.chart is None:
            result.pop('chart',None)
        if not self.text_spans:
            result.pop('text_spans',None)
        if not self.direct_edits:
            result.pop('direct_edits',None)
        return result

    @model_validator(mode='after')
    def _normalize_direct_edits(self):
        # 슬라이드만으로 정한다. 형식 등급(Deck)은 이 정규화 뒤의 값으로 계산된다 (재리뷰 RR6)
        if self.direct_edits:
            if isinstance(self.slots, DiagramSlots):
                raise ValueError('도식 페이지는 직접 수정을 지원하지 않습니다. 도식 작성 창에서 고쳐 주세요.')
            self.direct_edits = normalize_edits(self.direct_edits, frame_keys(self))
        return self

    @model_validator(mode='after')
    def expression_contract(self):
        if self.chart is not None and not isinstance(self.slots,TableSlots):
            raise ValueError('비교 차트는 원래 표 데이터를 보존하는 table 슬라이드에서만 사용할 수 있습니다.')
        if self.text_spans and isinstance(self.slots,DiagramSlots):
            raise ValueError('도식 문장의 부분 강조는 아직 지원하지 않습니다.')
        validate_spans(self)
        return self


class DeckMeta(BaseModel):
    title: str
    report_type: ReportType = "research"
    audience: str = ""  # 피보고자: 문체와 상세 수준의 기준으로만 쓰고 문서에 적지 않는다 (2026-09-01)
    presenter: str = ""  # 보고자(이름 또는 부서): 표지에 표기. 장 제목처럼 슬롯이 아니라 여기서 렌더한다 (2026-09-01 추가)
    preset_overrides: dict[str, Any] = {}
    # 보고 목적 (D3b-1, 계획 4.2). 기본값이면 직렬화하지 않는다. 구성 계획(ReportBrief)에 복사하지 않는다:
    # 0.2.0의 구성 계획 모델은 모르는 필드에서 검증이 실패한다
    # 스키마에서 기본값 표기를 뺀다: 기본값이면 응답에 키가 없으므로 화면 타입(openapi-typescript)이 "없을 수 있음"으로
    # 만들어야 한다. 기본값을 적어 두면 생성기가 항상 있는 값으로 만든다
    report_type_confirmed: bool = Field(default=False, json_schema_extra=_omittable)  # 형식 등급에는 넣지 않는다
    key_message: str = Field(default="", json_schema_extra=_omittable)  # 핵심 내용
    # None은 사용자가 고르지 않음(화면의 기본 표시: 사실 및 데이터 중심)
    desired_outcome: DesiredOutcome | None = Field(default=None, json_schema_extra=_omittable)
    # 기타를 고르지 않아도 지우지 않는다(제품 설계 6절)
    desired_outcome_other: str = Field(default="", json_schema_extra=_omittable)
    # 유형별 추가 입력. 키는 "유형.칸"(models/report_purpose.py)
    report_details: dict[str, str] = Field(default_factory=dict, json_schema_extra=_omittable)

    # 길이 상한은 문구를 직접 낸다. 기본 문구("입력 형식이 맞지 않습니다")로는 자동 저장의 422 원인을 알 수 없다
    # (D3b-1 리뷰 R12)
    @field_validator("key_message")
    @classmethod
    def _key_message_length(cls, value: str) -> str:
        if len(value) > KEY_MESSAGE_MAX:
            raise ValueError(f"핵심 내용은 {KEY_MESSAGE_MAX:,}자까지입니다")
        return value

    @field_validator("desired_outcome_other")
    @classmethod
    def _other_length(cls, value: str) -> str:
        if len(value) > OUTCOME_OTHER_MAX:
            raise ValueError(f"기타 설명은 {OUTCOME_OTHER_MAX:,}자까지입니다")
        return value

    @field_validator("report_details")
    @classmethod
    def _known_detail_fields(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - DETAIL_KEYS)
        if unknown:
            raise ValueError(f"알 수 없는 추가 입력 칸입니다: {', '.join(unknown)}")
        too_long = sorted(k for k, v in value.items() if len(v) > DETAIL_MAX)
        if too_long:
            raise ValueError(f"추가 입력은 칸마다 {DETAIL_MAX}자까지입니다: {', '.join(too_long)}")
        return {k: v for k, v in value.items() if not is_blank(v)}  # 비운 칸은 버린다 (재리뷰 RR5)

    @model_serializer(mode="wrap")
    def _omit_default_purpose(self, handler):
        payload = handler(self)
        for name, default in PURPOSE_DEFAULTS.items():
            if getattr(self, name) == default:
                payload.pop(name, None)
        return payload


class Deck(BaseModel):
    schema_version: int = SCHEMA_VERSION
    meta: DeckMeta
    structure: Structure = Structure()
    slides: list[Slide] = []
    document_review: 'DocumentChangeReview | None' = None

    @model_serializer(mode='wrap')
    def document_review_serialization(self,handler):
        payload=handler(self)
        if self.document_review is None:
            payload.pop('document_review',None)
        return payload

    @model_validator(mode="after")
    def _schema_version_supported(self) -> "Deck":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"이 덱 파일의 스키마 버전({self.schema_version})은 지원하지 않습니다. "
                f"이 앱은 버전 {SUPPORTED_SCHEMA_VERSIONS[-1]}까지 읽을 수 있습니다. "
                f"파일이 더 새 버전이라면 앱을 업데이트해 주세요."
            )
        # 입력값이 아니라 내용으로 정한다 (D3b-1). 저장, ETag 계산, 복원, CLI가 모두 이 검증을 거친다
        self.schema_version = {4: 3, 3: 2}.get(deck_level(self), 1)
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
            if isinstance(slide.slots, DiagramSlots):
                if slide.slots.diagram.id != chapter.id:
                    raise ValueError("도식 ID는 연결된 장 ID와 같아야 합니다")
                evidence = self.structure.story_plan.evidence if self.structure.story_plan else []
                parse_diagram_spec(slide.slots.diagram, evidence=evidence)
            if slide.chart is not None:
                plan=self.structure.story_plan
                comparison=next((c for c in plan.comparisons if c.id==slide.chart.comparison_id),None) if plan else None
                story_chapter=next((c for c in plan.chapters if c.chapter_id==slide.chapter_id),None) if plan else None
                if comparison is None or story_chapter is None or comparison.claim_id not in story_chapter.claim_ids:
                    raise ValueError('이 장의 기존 주장에 연결된 등록 비교를 선택해 주세요.')
        for chapter in self.structure.chapters:
            if chapter.template == "diagram":
                if chapter.id not in seen_slide_chapters:
                    raise ValueError(f"도식 장 {chapter.id}에는 도식 내용이 필요합니다")
                if not chapter.topic.strip():
                    raise ValueError("도식 장의 제목은 비어 있을 수 없습니다")
        return self
