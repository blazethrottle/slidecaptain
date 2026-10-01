"""Q3a 독립 도식 계약. 구조와 근거 ID만 검사하며 배치/의미 품질을 승인하지 않는다.

지원 진입점은 parse_diagram_spec(payload, evidence=...)다. 기존 Evidence 장부를
호출자가 제공해야 하며, 원문 대조와 관계 의미 검수는 별도 책임이다. 프로젝트의
DiagramInput은 Deck이 가진 단일 Evidence 장부로 같은 파서를 통과해야 한다.
"""

from collections.abc import Sequence
import json
from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, model_validator,
)

from slidecaptain.models.story import Evidence, Identifier, unique_ids


DiagramText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
EdgeLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class DiagramModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")


class DiagramCanvas(DiagramModel):
    # 수치의 진본은 Preset이다. 실제 페이지 크기와 읽기 프로필 적용은 후속 배치 단위다.
    page_size: Literal["preset"]
    reading_profile: Literal["report"]


class DiagramNode(DiagramModel):
    id: Identifier
    role: Literal["step", "entity", "decision", "outcome"]
    content: DiagramText
    kind: Literal["fact", "inference", "proposal", "unknown"]
    evidence_ids: list[Identifier]
    caveats: list[DiagramText]

    @model_validator(mode="after")
    def _support_and_uncertainty(self) -> "DiagramNode":
        unique_ids(self.evidence_ids, "노드의 근거")
        if self.kind == "fact" and not self.evidence_ids:
            raise ValueError("사실 노드는 원문 근거가 필요합니다")
        if self.kind in ("inference", "unknown") and not self.caveats:
            raise ValueError("추정과 미확인 노드는 조건이나 확인할 사항이 필요합니다")
        return self


class DiagramEdge(DiagramModel):
    id: Identifier
    from_node_id: Identifier
    to_node_id: Identifier
    relation: Literal["flow", "reference", "proposal"]
    label: EdgeLabel
    evidence_ids: list[Identifier]

    @model_validator(mode="after")
    def _support(self) -> "DiagramEdge":
        unique_ids(self.evidence_ids, "관계의 근거")
        if self.relation != "proposal" and not self.evidence_ids:
            raise ValueError("흐름과 참조 관계에는 관계 자체의 원문 근거가 필요합니다")
        if self.from_node_id == self.to_node_id:
            raise ValueError("관계를 자기 자신에게 연결할 수 없습니다")
        return self


class DiagramInput(DiagramModel):
    """저장할 의미 입력. 근거 ID의 존재 검사는 Deck 전체 또는 공개 파서가 수행한다."""

    version: Literal["q3a-v1"]
    id: Identifier
    canvas: DiagramCanvas
    nodes: list[DiagramNode] = Field(min_length=2, max_length=12)
    edges: list[DiagramEdge] = Field(min_length=1, max_length=24)
    # 지원하는 입력 이름이며, 레이아웃 구현이나 표시 검수의 통과 상태가 아니다.
    layout_variant: Literal["flow_horizontal"]

    @model_validator(mode="after")
    def _graph(self) -> "DiagramInput":
        node_ids = unique_ids([n.id for n in self.nodes], "노드")
        unique_ids([n.id for n in self.nodes] + [e.id for e in self.edges], "노드/관계")

        relations: set[tuple[str, str, str]] = set()
        following: dict[str, list[str]] = {nid: [] for nid in node_ids}
        incoming = dict.fromkeys(node_ids, 0)
        for edge in self.edges:
            if not {edge.from_node_id, edge.to_node_id} <= node_ids:
                raise ValueError(f"관계 {edge.id}이 존재하지 않는 노드를 가리킵니다")
            relation = (edge.from_node_id, edge.to_node_id, edge.relation)
            if relation in relations:
                raise ValueError("같은 방향과 종류의 관계가 중복되었습니다")
            relations.add(relation)
            if edge.relation == "flow":
                following[edge.from_node_id].append(edge.to_node_id)
                incoming[edge.to_node_id] += 1

        # Q3a의 flow는 순환 없는 순서 관계다. reference/proposal에는 순서를 부여하지 않는다.
        ready = [nid for nid, count in incoming.items() if count == 0]
        visited = 0
        while ready:
            nid = ready.pop()
            visited += 1
            for target in following[nid]:
                incoming[target] -= 1
                if incoming[target] == 0:
                    ready.append(target)
        if visited != len(node_ids):
            raise ValueError("Q3a 흐름 관계에는 순환을 넣을 수 없습니다")
        return self


class DiagramSpec(DiagramInput):
    @model_validator(mode="after")
    def _evidence_references(self, info: ValidationInfo) -> "DiagramSpec":
        if not isinstance(info.context, dict) or not isinstance(
            info.context.get("diagram_evidence_ids"), frozenset,
        ):
            raise ValueError("근거 장부를 parse_diagram_spec의 evidence 인수로 전달해야 합니다")
        evidence_ids = info.context["diagram_evidence_ids"]
        for item in [*self.nodes, *self.edges]:
            if not set(item.evidence_ids) <= evidence_ids:
                raise ValueError(f"도식 항목 {item.id}이 존재하지 않는 근거를 가리킵니다")
        return self


def _unique_json_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("도식 JSON 객체의 키가 중복되었습니다")
        result[key] = value
    return result


def _evidence_input(value: object, ancestors: set[int] | None = None) -> object:
    """기존 모델을 바꾸지 않고 재검증할 입력을 만든다. dump가 버리는 추가 필드도 보존한다."""
    if not isinstance(value, (BaseModel, dict, list, tuple)):
        return value
    ancestors = set() if ancestors is None else ancestors
    token = id(value)
    if token in ancestors:
        raise ValueError("근거 장부의 입력 객체가 순환합니다")
    ancestors.add(token)
    try:
        if isinstance(value, BaseModel):
            value = {**vars(value), **(value.model_extra or {})}
        if isinstance(value, dict):
            return {key: _evidence_input(item, ancestors) for key, item in value.items()}
        items = [_evidence_input(item, ancestors) for item in value]
        return tuple(items) if isinstance(value, tuple) else items
    finally:
        ancestors.remove(token)


def parse_diagram_spec(
    payload: dict | str | DiagramInput, *, evidence: Sequence[Evidence],
) -> DiagramSpec:
    """근거 장부와 입력 전체를 매번 재검증한다. 파일/모델 호출이나 입력 수정은 없다.

    Evidence의 위치/해시 형식과 ID 존재는 검사하지만 원문 파일의 현재성이나 관계의
    사실성을 검사하지 않는다. content/label은 실행하지 않는 평문이며 HTML로 렌더하지
    않는다. model_construct/model_copy로 검증을 우회해 만든 인스턴스도 이 진입점에서는
    미정의 필드를 버리지 않고 다시 검사한다. 반환 객체의 후속 편집은 다시 이 파서를 통과해야 한다.
    """
    checked_ids = []
    for item in evidence:
        if not isinstance(item, Evidence):
            raise ValueError("근거 장부에는 기존 Evidence 항목을 전달해야 합니다")
        checked = Evidence.model_validate(_evidence_input(item))
        checked_ids.append(checked.id)
    evidence_ids = frozenset(unique_ids(checked_ids, "근거 장부"))
    if isinstance(payload, str):
        payload = json.loads(payload, object_pairs_hook=_unique_json_members)
    if isinstance(payload, DiagramInput):
        payload = _evidence_input(payload)
    return DiagramSpec.model_validate(payload, context={"diagram_evidence_ids": evidence_ids})
