import type { CSSProperties } from "react";
import type { RenderPlan, SlidePlan } from "../api/client";

type Page = NonNullable<SlidePlan["diagram"]>;
type Text = Page["layout"]["nodes"][number]["texts"][number];

function textStyle(text: Text): CSSProperties {
  return {
    position: "absolute", left: text.bounds.x, top: text.bounds.y,
    width: text.bounds.w, height: text.bounds.h,
    fontSize: text.font_pt, lineHeight: `${text.line_height_pt}px`,
    fontWeight: text.bold ? 700 : 400, color: `#${text.color}`, whiteSpace: "pre",
  };
}

/** 읽기 전용 도식 레이어. 서버의 좌표와 줄바꿈을 그대로 표시한다. */
export function DiagramPreview({ page, style }: { page: Page; style: RenderPlan["style"] }) {
  const layout = page.layout;
  return <div role="group" aria-label="도식 미리보기"
    data-diagram-fingerprint={page.input_fingerprint}
    onClick={event => event.stopPropagation()}
    style={{ position: "absolute", inset: 0, background: `#${page.background}`,
      fontFamily: `"${layout.korean_font}", "${layout.latin_font}", sans-serif` }}>
    <svg width={layout.page_width_pt} height={layout.page_height_pt} aria-hidden="true"
      style={{ position: "absolute", inset: 0 }}>
      {layout.nodes.map(node => <rect key={node.node.id} data-diagram-node={node.node.id}
        data-evidence-ids={node.node.evidence_ids.join(" ")}
        x={node.bounds.x} y={node.bounds.y} width={node.bounds.w} height={node.bounds.h}
        fill={`#${node.fill}`} stroke={`#${node.border}`} strokeWidth={layout.border_width_pt} />)}
      {layout.edges.map(edge => <g key={edge.edge.id}>
        <line data-diagram-edge={edge.edge.id} data-evidence-ids={edge.edge.evidence_ids.join(" ")}
          x1={edge.start.point.x} y1={edge.start.point.y} x2={edge.end.point.x} y2={edge.end.point.y}
          stroke={`#${edge.color}`} strokeWidth={layout.border_width_pt} strokeLinecap={edge.line_cap}
          strokeDasharray={edge.dash_pattern_pt.length ? edge.dash_pattern_pt.join(" ") : "none"} />
        {edge.arrow_points.length > 0 && <polygon data-diagram-arrow={edge.edge.id}
          points={edge.arrow_points.map(p => `${p.x},${p.y}`).join(" ")}
          fill={`#${edge.color}`} stroke="none" />}
      </g>)}
    </svg>
    {layout.nodes.map(node => <div key={node.node.id} data-node-kind={node.node.kind}
      data-node-role={node.node.role} data-evidence-ids={node.node.evidence_ids.join(" ")}>
      {node.texts.map((text, index) => <div key={index} data-diagram-text={`${node.node.id}:${index}`}
        style={textStyle(text)}>{text.lines.join("\n")}</div>)}
    </div>)}
    {layout.edges.map(edge => <div key={edge.edge.id} data-diagram-label={edge.edge.id}
      data-from-node={edge.edge.from_node_id} data-to-node={edge.edge.to_node_id}
      data-evidence-ids={edge.edge.evidence_ids.join(" ")} style={textStyle(edge.label)}>
      {edge.label.lines.join("\n")}
    </div>)}
    {page.headers.map(frame => <div key={frame.name} data-diagram-header={frame.name}
      style={{ position: "absolute", left: frame.x, top: frame.y, width: frame.w, height: frame.h }}>
      {frame.paras.map((para, index) => <div key={index} style={{ fontSize: para.font_pt,
        lineHeight: `${para.font_pt * style.line_spacing}px`, fontWeight: para.bold ? 700 : 400,
        color: `#${para.color}`, textAlign: para.align, whiteSpace: "pre" }}>
        {para.lines.join("\n")}
      </div>)}
    </div>)}
  </div>;
}
