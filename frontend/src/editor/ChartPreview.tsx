import type { Frame } from "../api/client";

export function ChartPreview({frame}: {frame:Frame}) {
  const chart=frame.chart;
  if(!chart)return null;
  const y0=chart.plot_y+chart.plot_h;
  const font=chart.font_pt;
  // 값 축 글자는 0과 최댓값 둘이고 PowerPoint 실측 위치에 맞춘다(2026-10-20 회사 PC, build 20430, 12pt). 가로 막대는 눈금
  // 가운데 맞춤이고 획이 축 아래 14.5~23.5pt다. 세로 막대는 축 왼쪽 약 13.5pt에 끝 맞춤되고 획 가운데가 눈금 높이다
  const axisLabels=chart.kind === "bar"
    ? [{text:"0",x:chart.plot_x,y:y0+font*1.95},{text:chart.axis_maximum,x:chart.plot_x+chart.plot_w,y:y0+font*1.95}]
    : [{text:"0",x:chart.plot_x-font*1.125,y:y0+font/3},{text:chart.axis_maximum,x:chart.plot_x-font*1.125,y:chart.plot_y+font/3}];
  return <svg width={frame.w} height={frame.h} viewBox={`0 0 ${frame.w} ${frame.h}`} role="img"
    aria-label={`${chart.definition} 비교 차트. ${chart.points.map(p=>`${p.label} ${p.display}${chart.unit}`).join(", ")}. ${chart.conditions}`}>
    <line x1={chart.plot_x} y1={chart.plot_y} x2={chart.plot_x} y2={y0} stroke={`#${chart.text_color}`} />
    <line x1={chart.plot_x} y1={y0} x2={chart.plot_x+chart.plot_w} y2={y0} stroke={`#${chart.text_color}`} />
    {axisLabels.map((label,index)=><text key={index} x={label.x} y={label.y}
      textAnchor={chart.kind === "bar" ? "middle" : "end"} fill={`#${chart.text_color}`} fontSize={font}>{label.text}</text>)}
    {chart.points.map(point=><g key={point.evidence_id}>
      <rect x={point.x} y={point.y} width={point.w} height={point.h} fill={`#${point.color}`} />
      {chart.kind === "bar" ? <>
        <text x={chart.plot_x-chart.font_pt/2} y={point.y+point.h/2} textAnchor="end" dominantBaseline="middle" fontSize={chart.font_pt} fill={`#${chart.text_color}`}>{point.label}</text>
        <text x={point.x+point.w+chart.font_pt/2} y={point.y+point.h/2} dominantBaseline="middle" fontSize={chart.font_pt} fill={`#${chart.text_color}`}>{point.display}</text>
      </> : <>
        <text x={point.x+point.w/2} y={point.y-chart.font_pt/2} textAnchor="middle" fontSize={chart.font_pt} fill={`#${chart.text_color}`}>{point.display}</text>
        {/* 범주 이름 기준선은 축 아래 글자 크기의 2.1배다. PowerPoint는 12pt 범주 이름의 획을 축 아래 15.5~25.5pt에 그리고
            (2026-10-16 회사 PC, build 20430), 종전 1.5배의 미리보기 획은 8.05~18.52pt로 약 7pt 위였다 (2026-10-18 C3 측정) */}
        <text x={point.x+point.w/2} y={y0+chart.font_pt*2.1} textAnchor="middle" fontSize={chart.font_pt} fill={`#${chart.text_color}`}>{point.label}</text>
      </>}
    </g>)}
  </svg>;
}
