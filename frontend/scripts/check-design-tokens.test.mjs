// @vitest-environment node
// 디자인 토큰 검사 스크립트의 계약 시험 (D3a-1). 스크립트를 실제로 실행해 종료 코드와 출력으로 판정한다.
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("./check-design-tokens.mjs", import.meta.url));
const ROOT = `:root {
  --color-bg: #F4F6F8; --color-panel: #FFFFFF; --color-text: #172B4D; --color-text-muted: #526174;
  --color-border-strong: #7B8794; --color-primary: #244C83; --color-primary-hover: #193D70; --color-on-primary: #FFFFFF;
  --color-success: #176B55; --color-warning: #8A5700; --color-danger: #B42318; --color-accent-bg: #EEF3F9;
  --color-surface-subtle: #F8FAFC; --color-success-subtle: #EDF3EF; --color-focus: #517DC0;
  --space-2: 8px;
}
`;
let dir;
beforeAll(() => { dir = mkdtempSync(join(tmpdir(), "tokens-")); });
afterAll(() => { rmSync(dir, { recursive: true, force: true }); });

function run(body) {
  const file = join(dir, `case-${Math.random().toString(36).slice(2)}.css`);
  writeFileSync(file, ROOT + body);
  const result = spawnSync(process.execPath, [script, file], { encoding: "utf8" });
  return { code: result.status, out: result.stdout + result.stderr };
}

it("토큰만 쓴 크기, 1px 경계선, 매체 조건의 폭은 통과한다", () => {
  const { code, out } = run(`.a { padding: var(--space-2); border: 1px solid var(--color-border-strong); margin: 0; }
.b { width: 100%; } .c { margin: -1px; }
@media (max-width: 780px) { .a { padding: var(--space-2); } }
`);
  expect(out).toContain("통과");
  expect(code).toBe(0);
});

it.each([
  ["px", ".a { padding: 12px; }", "12px"],
  ["rem", ".a { margin-block: .75rem; }", ".75rem"],
  ["em", ".a { font-size: 0.9em; }", "0.9em"],
  ["음수", ".a { margin-left: -4px; }", "-4px"],
  ["매체 조건 안의 규칙 본문", "@media (max-width: 600px) { .a { padding: 14px; } }", "14px"],
  ["calc 안", ".a { max-height: calc(100dvh - 32px); }", "32px"],
])("토큰 밖의 직접 크기(%s)를 잡는다", (_name, body, value) => {
  const { code, out } = run(body + "\n");
  expect(code).toBe(1);
  expect(out).toContain(`토큰 밖의 직접 크기 ${value}`);
});

it("주석 속 크기 값은 세지 않는다", () => {
  const { code } = run("/* 시안 값 12px */ .a { padding: var(--space-2); }\n");
  expect(code).toBe(0);
});

it("행 번호와 합계를 보고한다", () => {
  const { code, out } = run(".a { padding: 12px 16px; }\n");
  expect(code).toBe(1);
  expect(out).toMatch(/styles\.css \d+행: 토큰 밖의 직접 크기 12px, 16px/);
  expect(out).toContain("직접 크기 값 합계 2개");
});
