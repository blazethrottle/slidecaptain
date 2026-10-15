// 도식 후보 다시 열기의 시작값 규칙 (C1 계획 W2-b, 4.3)
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import type { Deck } from "../api/client";
import { jobView } from "../test/jobs";
import { emptyUsage } from "../test/usage";
import { reopenDiagram, reopenRefusal } from "./diagramReopen";

const deck = fixture.deck as Deck;
const result = { status: "ok", diagram: { nodes: [], edges: [] }, raw_text: "", unverified_numbers: [], format_retried: false,
  usage: emptyUsage(), base_etag: '"base"', sources_fingerprint: "s" };
const job = (params: Record<string, unknown>, over = {}) => jobView("diagram", { id: "job-d1", params, relevance_hash: "d1:a|b",
  result, ...over });

it("새 도식은 요청의 제목, 역할, 주장, 지시로 시작하고 장 ID가 비어 있으면 그 ID를 쓴다", () => {
  const opened = reopenDiagram(job({ mode: "create", chapter_id: "new-diagram", topic: "요청 제목", role: "risk",
    claim_ids: ["claim"], instructions: "지시" }), deck)!;
  expect(opened.draft).toMatchObject({ id: "new-diagram", isNew: true, topic: "요청 제목", storyRole: "risk", claimIds: ["claim"] });
  expect(opened.candidate).toMatchObject({ jobId: "job-d1", instructions: "지시" });
});

it("새 도식의 장 ID를 그사이 다른 장이 쓰면 새 번호를 쓴다", () => {
  const opened = reopenDiagram(job({ mode: "create", chapter_id: "synthetic-flow", topic: "t", role: "risk", claim_ids: [] }), deck)!;
  expect(opened.draft.id).not.toBe("synthetic-flow");
  expect(deck.structure.chapters.some((c) => c.id === opened.draft.id)).toBe(false);
});

it("mode 칸이 없는 옛 행도 새 도식으로 본다", () => {
  expect(reopenDiagram(job({ chapter_id: "new-diagram", topic: "t", role: "risk", claim_ids: [] }), deck)?.draft.isNew).toBe(true);
});

it("교체는 지금 덱의 도식에서 시작하고 요청의 제목과 연결로 덮지 않는다", () => {
  const opened = reopenDiagram(job({ mode: "replace", chapter_id: "synthetic-flow", topic: "요청 때의 제목", role: "risk",
    claim_ids: ["다른 주장"] }), deck)!;
  expect(opened.draft.isNew).toBe(false);
  expect(opened.draft.topic).toBe("요청 처리 흐름");
  expect(opened.draft.claimIds).not.toContain("다른 주장");
});

it("교체 대상이 덱에 없으면 열지 않고, 처분과 사유와 결과가 맞지 않는 행은 이유를 돌려준다", () => {
  expect(reopenDiagram(job({ mode: "replace", chapter_id: "없는-장" }), deck)).toBeNull();
  expect(reopenRefusal(job({}, { candidate_status: "stale" }))).toMatch(/만든 뒤 입력이 바뀐/);
  expect(reopenRefusal(job({}, { stale_reasons: ["chapter_changed"] }))).toMatch(/만든 뒤 입력이 바뀐/);
  expect(reopenRefusal(job({}, { relevance_hash: "c1:x" }))).toMatch(/이전 버전/);
  expect(reopenRefusal(job({}, { result: { ...result, status: "format_error", diagram: null } }))).toMatch(/불러올 도식이 없는/);
  expect(reopenRefusal(job({}, { stale_reasons: ["deck_changed_elsewhere"] }))).toBeNull();
  expect(reopenRefusal(job({}, { candidate_status: "applied" }))).toMatch(/이미 처리한/);
});
