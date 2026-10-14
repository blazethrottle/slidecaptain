// 장 후보의 반영 단위 (D3c-6, 계획 4.8). 서버의 pipeline/candidate_apply.py MERGE_UNITS와 같은 표이고 고정 파일
// backend/tests/fixtures/merge-units.json으로 묶는다(mergeUnits.test.ts). 문구 칸 하나가 한 단위이고, 목록은 목록 전체가 한
// 단위이며, 표는 열과 행을 함께 한 단위로 본다. 색 역할(tone)은 그 칸이 든 단위를 따라간다
import { roleName } from "./directEdit";

export const MERGE_UNITS: Record<string, Record<string, string[]>> = {
  cover: { title: ["title"], subtitle: ["subtitle"], date: ["date"] },
  summary: { conclusion: ["conclusion"], points: ["points"] },
  bullet_box: { bullets: ["bullets"], conclusion: ["conclusion"], footnote: ["footnote"] },
  table: { table: ["columns", "rows"], footnote: ["footnote"] },
  compare2: { left: ["left"], right: ["right"], conclusion: ["conclusion"] },
  divider: { section_no: ["section_no"], section_title: ["section_title"] },
  callout: { text: ["text", "tone"] },
  cards: { cards: ["cards"] },
  process: { steps: ["steps"] },
  matrix: { rows: ["rows"] },
};

// 요소 이름 표(roleName)에 없는 단위 이름. 목록 단위는 그 안의 항목 상자와 구별되게 "전체"를 붙인다
const UNIT_NAMES: Record<string, string> = {
  left: "왼쪽 카드", right: "오른쪽 카드", cards: "카드 전체", steps: "단계 전체",
};

export function unitName(template: string, unit: string): string {
  if (template === "cover" && unit === "title") return roleName("cover_title");
  if (template === "matrix" && unit === "rows") return "분류 행 전체";
  return UNIT_NAMES[unit] ?? roleName(unit, template);
}

// 단위가 담은 글자만 모은다. 사용자가 고를 때는 구조보다 내용이 필요하다
export function unitText(slots: Record<string, unknown> | null | undefined, template: string, unit: string): string {
  if (!slots) return "";
  const texts: string[] = [];
  const walk = (value: unknown, key = "") => {
    if (typeof value === "string") { if (value.trim() && key !== "template" && key !== "tone") texts.push(value); }
    else if (Array.isArray(value)) value.forEach((v) => walk(v));
    else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => walk(v, k));
  };
  for (const field of MERGE_UNITS[template]?.[unit] ?? []) walk(slots[field], field);
  return texts.join("\n");
}
