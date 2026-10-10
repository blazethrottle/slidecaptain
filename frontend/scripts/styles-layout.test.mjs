// @vitest-environment node
// 다섯 단계 셸의 배치 경계 규칙 (D3a-2, 계획 4.1, 시안 두 매체 조건). 화면 폭에 따른 실제 배치는 jsdom이 계산하지
// 못한다. 배치 수치는 헤드리스 Chromium 측정으로 확인하고, 여기서는 경계 규칙이 styles.css에 있음을 지킨다
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const css = readFileSync(fileURLToPath(new URL("../src/styles.css", import.meta.url)), "utf8");

it("1100px 이하에서 단계 목록을 줄이고, 780px 이하에서 가로 띠로 바꾼다", () => {
  expect(css).toMatch(/@media \(max-width: 1100px\) \{\s*\.project-shell \{ grid-template-columns: var\(--width-sidebar-narrow\)/);
  expect(css).toMatch(/@media \(max-width: 780px\) \{\s*\.project-shell \{ grid-template-columns: minmax\(0, 1fr\);/);
});

it("편집 화면의 쌓임은 뷰포트가 아니라 본문 폭(컨테이너 조건)으로 정한다", () => {
  expect(css).toMatch(/\.stage-body \{[^}]*container: stage \/ inline-size;/);
  expect(css).toMatch(/@container stage \(max-width: 1080px\) \{\s*\.editor-screen/);
  expect(css).toMatch(/@container stage \(max-width: 748px\) \{\s*\.editor-screen/);
  expect(css).not.toMatch(/@media \(max-width: 1000px\)/);
});
