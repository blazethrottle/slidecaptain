// 화면의 반영 단위 표가 서버 표(고정 파일)와 같은지 지킨다 (D3c-6)
import fixture from "../../../backend/tests/fixtures/merge-units.json";
import { MERGE_UNITS, unitName, unitText } from "./mergeUnits";

test("반영 단위 표가 서버의 고정 파일과 같다", () => {
  expect(MERGE_UNITS).toEqual(fixture.units);
});

test("단위마다 우리말 이름이 있고 열쇠 이름이 그대로 보이지 않는다", () => {
  for (const [template, units] of Object.entries(MERGE_UNITS)) {
    for (const unit of Object.keys(units)) expect(unitName(template, unit)).not.toBe(unit);
  }
  expect(unitName("cover", "title")).toBe("표지 제목");
  expect(unitName("cover", "subtitle")).toBe("표지 부제");
  expect(unitName("cards", "cards")).toBe("카드 전체");
});

test("단위 글자는 그 칸의 문구만 모으고 색 역할 이름은 뺀다", () => {
  expect(unitText({ template: "callout", text: "핵심", tone: "danger" }, "callout", "text")).toBe("핵심");
  expect(unitText({ template: "table", columns: ["구분"], rows: [["A"]], footnote: "출처" }, "table", "table")).toBe("구분\nA");
});
