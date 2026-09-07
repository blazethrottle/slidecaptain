import type { TemplateName } from "../api/client";

export const TEMPLATE_LABELS: Record<TemplateName, string> = {
  cover: "표지",
  summary: "핵심 요약",
  bullet_box: "불릿 + 강조박스",
  table: "표 중심",
  compare2: "2단 비교",
  divider: "간지",
  callout: "강조 밴드",
  cards: "카드 나열",
};

// 구조안 화면과 속성 패널의 템플릿 드롭다운이 고를 수 있는 목록. TEMPLATE_LABELS 와 분리한
// 이유: 새 템플릿의 편집 UI(속성 패널 분기, 항목 추가와 삭제)는 DB-6 소관이라, 여기서
// 고르면 편집할 수단이 없는 상태가 된다. DB-6 이 새 템플릿을 준비되는 대로 여기에 더한다.
// cards(DB-2)도 같은 이유로 아직 넣지 않는다.
export const SELECTABLE_TEMPLATES: TemplateName[] = [
  "cover", "summary", "bullet_box", "table", "compare2", "divider",
];
