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
  process: "번호 단계",
  matrix: "분류 매트릭스",
  diagram: "관계 도식",
};

// 의미 입력 도식은 별도 작성창에서 다룬다. 나머지 템플릿은 속성 편집을 제공한다.
export const SELECTABLE_TEMPLATES: TemplateName[] = [
  "cover", "summary", "bullet_box", "table", "compare2", "divider", "callout", "cards", "process", "matrix",
];
