// 디자인 토큰 검사 (개정판 D2a-4).
// 화면 시험(vitest, jsdom)은 styles.css를 읽거나 var()를 풀지 못하므로 Node 스크립트로 검사한다.
// 검사: (1) 대비 계산 자기 검사 (2) 글자 색 대비 4.5:1 (3) 초점선과 컴포넌트 경계 3:1
// (4) :root 토큰 블록 밖의 hex, rgb(), rgba(), 이름 색 금지. 의존성은 쓰지 않는다.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// 검사 대상은 기본으로 src/styles.css다. 첫 인자로 다른 파일을 줄 수 있다(검사 스크립트 자체의 시험용)
const cssPath = process.argv[2] ?? fileURLToPath(new URL("../src/styles.css", import.meta.url));
// 주석을 먼저 지운다: 주석 처리한 토큰을 정의로 읽거나 주석 속 색을 직접 색으로 세지 않게 (D2a-4 리뷰 R4)
// 줄바꿈은 남겨 오류의 행 번호가 원래 파일과 맞게 한다
const css = readFileSync(cssPath, "utf8").replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, ""));
const failures = [];

function luminance(hex) {
  const value = hex.replace("#", "");
  const full = value.length === 3 ? [...value].map((c) => c + c).join("") : value.slice(0, 6);
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255)
    // WCAG 2 정의의 경계값 0.03928. sRGB 표준은 0.04045지만 8비트 색에서는 두 경계 사이의 값이 없다
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// (1) 계산 함수 자기 검사: 흑백 21:1, 같은 색 1:1 (WCAG 2 정의)
if (Math.abs(contrast("#000000", "#FFFFFF") - 21) > 0.01) failures.push("대비 계산이 흑백 21:1을 내지 않습니다");
if (Math.abs(contrast("#526174", "#526174") - 1) > 0.001) failures.push("대비 계산이 같은 색 1:1을 내지 않습니다");

const rootMatch = css.match(/:root\s*\{([^}]*)\}/);
const tokens = {};
if (!rootMatch) {
  failures.push(":root 토큰 블록이 없습니다");
} else {
  for (const m of rootMatch[1].matchAll(/--([a-z0-9-]+)\s*:\s*([^;]+);/g)) tokens[m[1]] = m[2].trim();
}
const color = (name) => {
  const value = tokens[name];
  if (!value || !/^#[0-9a-fA-F]{6}$/.test(value)) {
    failures.push(`색 토큰 --${name}이 없거나 6자리 hex가 아닙니다 (${value ?? "없음"})`);
    return null;
  }
  return value;
};

// (2) 글자 색: 배경과 패널, 옅은 강조 배경 위에서 4.5:1 이상
const surfaces = ["color-bg", "color-panel", "color-accent-bg", "color-surface-subtle", "color-success-subtle"];
const textColors = ["color-text", "color-text-muted", "color-primary", "color-success", "color-warning", "color-danger"];
for (const fg of textColors) {
  for (const bg of surfaces) {
    const [a, b] = [color(fg), color(bg)];
    if (a && b && contrast(a, b) < 4.5) failures.push(`--${fg} / --${bg} 대비 ${contrast(a, b).toFixed(2)} < 4.5`);
  }
}
const onPrimary = [color("color-on-primary"), color("color-primary")];
if (onPrimary.every(Boolean) && contrast(...onPrimary) < 4.5) failures.push("주 행동 버튼 글자 대비 < 4.5");

// (3) 비텍스트: 초점선과 컴포넌트 경계는 배경과 패널 위에서 3:1 이상 (WCAG 1.4.11)
for (const fg of ["color-focus", "color-border-strong"]) {
  for (const bg of surfaces) {
    const [a, b] = [color(fg), color(bg)];
    if (a && b && contrast(a, b) < 3) failures.push(`--${fg} / --${bg} 대비 ${contrast(a, b).toFixed(2)} < 3`);
  }
}

// (4) 토큰 블록 밖의 직접 색 금지
const outside = rootMatch ? css.replace(rootMatch[0], rootMatch[0].replace(/[^\n]/g, "")) : css;
// 이름 색은 선언 값에서만 찾는다(white-space 같은 속성 이름을 색으로 오인하지 않게). CSS 이름 색 전체 목록이다
const NAMED = "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen".split(" ");
const named = new RegExp("(?<![-\\w])(" + NAMED.join("|") + ")(?![-\\w])", "i");
const colorFunction = /\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix)\(/i;  // 리뷰 R3
outside.split("\n").forEach((line, i) => {
  const code = line.replace(/\/\*.*?\*\//g, "");
  const values = [...code.matchAll(/[a-z-]+\s*:\s*([^;{}]+)/g)].map((m) => m[1]);
  if (/#[0-9a-fA-F]{3,8}\b/.test(code) || colorFunction.test(code) || values.some((v) => named.test(v))) {
    failures.push(`styles.css ${i + 1}행: 토큰 밖의 직접 색 ${code.trim()}`);
  }
});

if (failures.length) {
  console.error(`디자인 토큰 검사 실패 ${failures.length}건`);
  for (const f of failures) console.error(" - " + f);
  process.exit(1);
}
console.log(`디자인 토큰 검사 통과: 토큰 ${Object.keys(tokens).length}개`);
