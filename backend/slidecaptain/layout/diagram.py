"""Q3b 한 줄 도식 배치. 의미/근거 검수와 실제 렌더는 수행하지 않는다.

지원하지 않는 토폴로지와 용량 부족은 부분 도식을 만들지 않고 사유로 반환한다.
독립 출력이며 기존 Deck/RenderPlan/HTTP 계약에는 연결하지 않는다.
"""

from collections import Counter
from collections.abc import Sequence
import hashlib
import heapq
import json
import math

from slidecaptain.metrics.font_metrics import FaceMetrics, FontMetrics, HANGUL_END, HANGUL_START
from slidecaptain.metrics.line_breaker import break_paragraph
from slidecaptain.models.diagram import DiagramSpec, _evidence_input, parse_diagram_spec
from slidecaptain.models.diagram_render import (
    DiagramAnchor, DiagramBounds, DiagramEdgePlan, DiagramLayoutIssue, DiagramLayoutResult,
    DiagramNodePlan, DiagramPoint, DiagramRenderPlan, DiagramTextPlan,
)
from slidecaptain.models.preset import Preset
from slidecaptain.layout.templates import slide_geometry
from slidecaptain.models.story import Evidence


_KINDS = {"fact": "사실", "inference": "추정", "proposal": "제안", "unknown": "미확인"}
_ROLES = {"step": "단계", "entity": "주체", "decision": "판단", "outcome": "결과"}
_RELATIONS = {"flow": "흐름", "reference": "참조", "proposal": "제안"}
_STROKES = {"flow": "solid", "reference": "dotted", "proposal": "dashed"}


def _metrics_snapshot(metrics: FontMetrics) -> FontMetrics:
    if not isinstance(metrics, FontMetrics):
        raise ValueError("FontMetrics 폭 수치가 필요합니다")
    faces = []
    for face in (getattr(metrics, "regular", None), getattr(metrics, "bold", None)):
        if not isinstance(face, FaceMetrics) or not all(
            hasattr(face, field) for field in ("upem", "widths", "hangul_uniform_width", "fallback_width")
        ):
            raise ValueError("폰트 수치의 regular와 bold가 필요합니다")
        positive = [face.upem, face.fallback_width]
        if face.hangul_uniform_width is not None:
            positive.append(face.hangul_uniform_width)
        if any(type(v) is not int or v <= 0 for v in positive):
            raise ValueError("폰트 단위와 기본 폭은 양의 정수여야 합니다")
        if not isinstance(face.widths, dict) or any(
            type(k) is not int or not 0 <= k <= 0x10FFFF or type(v) is not int or v <= 0
            for k, v in face.widths.items()
        ):
            raise ValueError("글자 폭 표의 코드와 수치가 잘못되었습니다")
        advances = [*face.widths.values(), face.fallback_width]
        if face.hangul_uniform_width is not None:
            advances.append(face.hangul_uniform_width)
        try:
            ratios = [advance / face.upem for advance in advances]
        except OverflowError as exc:
            raise ValueError("글자 폭을 유한한 수치로 계산할 수 없습니다") from exc
        if any(not math.isfinite(ratio) or ratio <= 0 for ratio in ratios):
            raise ValueError("글자 폭은 정규화 후에도 유한한 양수여야 합니다")
        # 호출자의 가변 수치나 사용자 정의 메서드를 계산 도중 다시 참조하지 않는다.
        faces.append(FaceMetrics(face.upem, dict(face.widths), face.hangul_uniform_width, face.fallback_width))
    return FontMetrics(*faces)


def _ordered_nodes(spec: DiagramSpec):
    positions = {node.id: i for i, node in enumerate(spec.nodes)}
    incoming = dict.fromkeys(positions, 0)
    following = {node.id: [] for node in spec.nodes}
    for edge in spec.edges:
        if edge.relation == "flow":
            incoming[edge.to_node_id] += 1
            following[edge.from_node_id].append(edge.to_node_id)
    ready = [positions[nid] for nid, count in incoming.items() if count == 0]
    heapq.heapify(ready)
    result = []
    while ready:
        node = spec.nodes[heapq.heappop(ready)]
        result.append(node)
        for target in following[node.id]:
            incoming[target] -= 1
            if incoming[target] == 0:
                heapq.heappush(ready, positions[target])
    return result


def _supported_text(text: str, face: FaceMetrics) -> bool:
    # break_paragraph가 축약하는 공백은 성공으로 측정하지 않는다.
    if any("  " in line or line != line.strip(" ") for line in text.split("\n")):
        return False
    for char in text:
        cp = ord(char)
        if char == "\n":
            continue
        if cp < 32 or cp == 127:
            return False
        if cp in face.widths:
            continue
        if HANGUL_START <= cp <= HANGUL_END and face.hangul_uniform_width is not None:
            continue
        return False  # 폴백 폭은 실제 글리프의 폭/존재를 입증하지 않는다.
    return True


def build_diagram_layout(
    payload: dict | str | DiagramSpec, preset: Preset, metrics: FontMetrics,
    *, evidence: Sequence[Evidence], eyebrow: str = "", subtitle: str = "",
) -> DiagramLayoutResult:
    """입력을 재검증해 계산하거나 typed blocked를 반환한다. 파일/AI 호출과 입력 수정은 없다.

    입력 도식/근거/프리셋/폰트 수치가 잘못됐으면 ValueError다. computed도 단일 행
    계산 후보일 뿐이며 의미, 브라우저, 목표 PowerPoint와 독자 검수는 not_run이다.
    """
    spec = parse_diagram_spec(payload, evidence=evidence)
    if not isinstance(preset, Preset):
        raise ValueError("Preset 입력이 필요합니다")
    # model_dump가 누락할 수 있는 미정의 필드도 보존하는 Q3a의 재검증 경계를 공유한다.
    preset = Preset.model_validate(_evidence_input(preset))
    metrics = _metrics_snapshot(metrics)
    if not isinstance(eyebrow, str) or not isinstance(subtitle, str):
        raise ValueError("분류 라벨과 부제는 문자열이어야 합니다")
    fingerprint_data = {
        "rule_version": "q3b-v1", "diagram": spec.model_dump(mode="json"),
        "preset": preset.model_dump(mode="json"),
        "evidence": [Evidence.model_validate(_evidence_input(e)).model_dump(mode="json") for e in evidence],
        "metrics": json.loads(metrics.to_json()),
    }
    if eyebrow or subtitle:
        fingerprint_data["common_slots"] = {"eyebrow": eyebrow, "subtitle": subtitle}
    fingerprint = hashlib.sha256(json.dumps(
        fingerprint_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    issues: list[DiagramLayoutIssue] = []

    def issue(code, target, message, needed=None, available=None):
        issues.append(DiagramLayoutIssue(
            code=code, target_id=target, message=message,
            needed_pt=needed if needed is None or math.isfinite(needed) else None,
            available_pt=available if available is None or math.isfinite(available) else None,
        ))

    def blocked():
        return DiagramLayoutResult(
            diagram_id=spec.id, input_fingerprint=fingerprint, status="blocked", plan=None, issues=issues,
        )

    if preset.fonts.korean != "Noto Sans KR" or preset.fonts.latin != "Noto Sans KR":
        issue("unsupported_font", spec.id, "현재 도식 배치는 Noto Sans KR 폭 수치만 지원합니다.")
    if preset.spacing.line_spacing < 1:
        issue("unsupported_spacing", spec.id, "도식의 줄 높이는 글자 크기보다 작을 수 없습니다.")
    nodes = _ordered_nodes(spec)
    positions = {node.id: i for i, node in enumerate(nodes)}
    groups = [[] for _ in range(len(nodes) - 1)]
    for edge in spec.edges:
        a, b = positions[edge.from_node_id], positions[edge.to_node_id]
        if abs(a - b) != 1:
            issue("unsupported_topology", edge.id, "첫 도식 배치는 한 줄의 인접한 노드 연결만 지원합니다.")
        else:
            groups[min(a, b)].append(edge)
    if issues:
        return blocked()

    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = slide_geometry(preset, eyebrow, subtitle)
    stroke = s.border_width_pt
    # 테두리 외곽까지 본문 안에 두기 위해 중심 좌표에서 반 굵기를 예약한다.
    left, top = s.margin_left + stroke / 2, g["content_top"] + stroke / 2
    width = g["content_width"] - stroke
    height = g["content_bottom"] - g["content_top"] - stroke
    gap = max(s.card_gap, width / (3 * len(nodes) - 1))
    node_width = (width - gap * (len(nodes) - 1)) / len(nodes)
    padding = max(s.box_padding, stroke, r.body_pt / 2)
    arrow_size = max(r.body_pt / 2, stroke * 2)
    text_width, label_width = node_width - padding * 2, gap - padding * 2
    if not all(math.isfinite(v) for v in (left, top, width, height, gap, node_width, padding, arrow_size)):
        issue("invalid_geometry", spec.id, "페이지와 간격에서 유한한 도식 좌표를 계산할 수 없습니다.")
        return blocked()
    if min(text_width, label_width, height) <= 0 or gap < arrow_size + stroke:
        issue("width_overflow", spec.id, "본문 폭과 간격에 노드, 관계와 테두리를 배치할 수 없습니다.")
        return blocked()

    def measure(text, width, font, bold, target):
        face = metrics.face(bold)
        if not _supported_text(text, face):
            issue("unsupported_text", target, "공백이 축약되거나 폭이 확인되지 않은 문자가 있어 배치할 수 없습니다.")
            return None
        try:
            lines = break_paragraph(text, width, font, face, s.safety_ratio)
            needed_width = max(face.width_pt(line, font) for line in lines)
            line_height = font * s.line_spacing
            needed_height = len(lines) * line_height
        except OverflowError:
            issue("invalid_geometry", target, "폰트 수치로 유한한 글자 크기를 계산할 수 없습니다.")
            return None
        if not all(math.isfinite(v) for v in (needed_width, line_height, needed_height)):
            issue("invalid_geometry", target, "유한한 글자 폭과 높이를 계산할 수 없습니다.")
            return None
        if needed_width > width * s.safety_ratio + 1e-8:
            issue("width_overflow", target, "한 글자의 폭이 텍스트 영역을 초과합니다.", needed_width, width * s.safety_ratio)
            return None
        return DiagramTextPlan(
            text=text, lines=lines, bounds=DiagramBounds(x=0.0, y=0.0, w=width, h=needed_height),
            font_pt=font, line_height_pt=line_height, bold=bold, color=c.text,
        )

    counts = Counter(node.content for node in nodes)
    names = {node.id: node.content if counts[node.content] == 1 else f"{node.content} ({node.id})" for node in nodes}
    if len(set(names.values())) != len(nodes):
        # 추가한 식별 접미사와 다른 원래 content가 우연히 같아지는 경우도 구분한다.
        names = {node.id: f"[{node.id}] {node.content}" for node in nodes}
    node_texts = {}
    for node in nodes:
        entries = [(f"{_KINDS[node.kind]} / {_ROLES[node.role]}", True), (names[node.id], False)]
        entries.extend((f"조건: {caveat}", False) for caveat in node.caveats)
        node_texts[node.id] = [measure(text, text_width, r.box_pt, bold, node.id) for text, bold in entries]
    labels = {}
    for edge in spec.edges:
        text = f"{_RELATIONS[edge.relation]}: {edge.label}"
        if edge.relation != "flow":
            text += f"\n주체: {names[edge.from_node_id]}\n대상: {names[edge.to_node_id]}"
        labels[edge.id] = measure(text, label_width, r.body_pt, False, edge.id)
    if issues:
        return blocked()

    node_heights = {
        nid: sum(t.bounds.h for t in texts) + padding * (len(texts) + 1)
        for nid, texts in node_texts.items()
    }
    # 레인마다 라벨, 선과 화살표 외곽, 다음 라벨의 여유를 모두 예약한다.
    lane_heights = {edge.id: labels[edge.id].bounds.h + padding * 3 + arrow_size for edge in spec.edges}
    group_heights = [sum(lane_heights[edge.id] for edge in group) for group in groups]
    row_height = max(*node_heights.values(), *group_heights)
    if not math.isfinite(row_height):
        issue("invalid_geometry", spec.id, "유한한 도식 높이를 계산할 수 없습니다.")
        return blocked()
    if row_height > height:
        for target, needed in node_heights.items():
            if needed > height:
                issue("height_overflow", target, "노드 본문과 조건이 본문 높이를 초과합니다.", needed, height)
        for group, needed in zip(groups, group_heights):
            if needed > height:
                for edge in group:
                    issue("height_overflow", edge.id, "관계 라벨과 연결선 레인이 본문 높이를 초과합니다.", needed, height)
        return blocked()

    row_top = top + (height - row_height) / 2
    rendered_nodes = []
    for i, node in enumerate(nodes):
        x = left + i * (node_width + gap)
        y = row_top + padding
        for text in node_texts[node.id]:
            text.bounds = DiagramBounds(x=x + padding, y=y, w=text_width, h=text.bounds.h)
            y += text.bounds.h + padding
        rendered_nodes.append(DiagramNodePlan(
            node=node, display_name=names[node.id],
            bounds=DiagramBounds(x=x, y=row_top, w=node_width, h=row_height),
            texts=node_texts[node.id], fill=c.box_fill, border=c.border,
        ))
    boxes = {n.node.id: n.bounds for n in rendered_nodes}
    rendered_edges = {}
    for i, group in enumerate(groups):
        lane_top = row_top + (row_height - group_heights[i]) / 2
        gap_left = rendered_nodes[i].bounds.x + node_width
        for edge in group:
            label = labels[edge.id]
            label.bounds = DiagramBounds(x=gap_left + padding, y=lane_top + padding, w=label_width, h=label.bounds.h)
            line_y = label.bounds.y + label.bounds.h + padding + arrow_size / 2
            forward = positions[edge.from_node_id] < positions[edge.to_node_id]
            source, target = boxes[edge.from_node_id], boxes[edge.to_node_id]
            start = DiagramAnchor(side="right" if forward else "left", point=DiagramPoint(
                x=source.x + source.w if forward else source.x, y=line_y,
            ))
            end = DiagramAnchor(side="left" if forward else "right", point=DiagramPoint(
                x=target.x if forward else target.x + target.w, y=line_y,
            ))
            arrow = []
            if edge.relation == "flow":
                base_x = end.point.x - arrow_size if forward else end.point.x + arrow_size
                arrow = [end.point, DiagramPoint(x=base_x, y=line_y - arrow_size / 2),
                         DiagramPoint(x=base_x, y=line_y + arrow_size / 2)]
            rendered_edges[edge.id] = DiagramEdgePlan(
                edge=edge, start=start, end=end, label=label,
                stroke=_STROKES[edge.relation], color=c.text, arrow_points=arrow,
                dash_pattern_pt={"flow": [], "reference": [stroke, stroke * 3],
                                 "proposal": [stroke * 4, stroke * 3]}[edge.relation],
                line_cap="butt",
            )
            lane_top += lane_heights[edge.id]
    plan = DiagramRenderPlan(
        diagram_id=spec.id, page_width_pt=preset.page_width_pt, page_height_pt=preset.page_height_pt,
        content_bounds=DiagramBounds(x=s.margin_left, y=g["content_top"], w=g["content_width"],
                                     h=g["content_bottom"] - g["content_top"]),
        korean_font=preset.fonts.korean, latin_font=preset.fonts.latin, border_width_pt=stroke,
        nodes=rendered_nodes, edges=[rendered_edges[e.id] for e in spec.edges],
    )
    # 산식 변경 뒤에도 모든 외곽이 본문 안에 있는지 독립 대조한다.
    points = []
    for node in plan.nodes:
        b = node.bounds
        points.extend([(b.x - stroke / 2, b.y - stroke / 2),
                       (b.x + b.w + stroke / 2, b.y + b.h + stroke / 2)])
        for text in node.texts:
            b = text.bounds
            points.extend([(b.x, b.y), (b.x + b.w, b.y + b.h)])
    for edge in plan.edges:
        b = edge.label.bounds
        points.extend([(b.x, b.y), (b.x + b.w, b.y + b.h)])
        for p in [edge.start.point, edge.end.point, *edge.arrow_points]:
            points.extend([(p.x - stroke / 2, p.y - stroke / 2), (p.x + stroke / 2, p.y + stroke / 2)])
    bounds = plan.content_bounds
    if any(not math.isfinite(x) or not math.isfinite(y) or
           x < bounds.x - 1e-8 or y < bounds.y - 1e-8 or
           x > bounds.x + bounds.w + 1e-8 or y > bounds.y + bounds.h + 1e-8 for x, y in points):
        issue("invalid_geometry", spec.id, "계산된 도식의 외곽이 본문 경계를 벗어납니다.")
        return blocked()
    return DiagramLayoutResult(
        diagram_id=spec.id, input_fingerprint=fingerprint, status="computed", plan=plan, issues=[],
    )
