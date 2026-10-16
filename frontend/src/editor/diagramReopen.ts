// 작성 창을 닫은 뒤 남은 도식 AI 후보를 다시 여는 규칙 (C1 계획 W2-b, 4.3). 복구 화면의 버튼 조건과 편집 화면의 시작값이
// 같은 판정을 쓴다. D2b-5b 정정 8이 남긴 "대화 상자의 입력과 후보의 입력을 맞추는 규칙"이다
import type { Deck, DiagramGenerationResult, JobView } from "../api/client";
import { blockingReasons } from "../api/jobs";
import { createDiagramDraft, editDiagramDraft, type DiagramDraft, type StoryRole } from "./diagramDraft";

export type ReopenedDiagram = { jobId: string; result: DiagramGenerationResult; instructions: string };

type DiagramParams = { mode?: string; chapter_id?: string; topic?: string; role?: string; claim_ids?: string[];
  instructions?: string };

// 다시 열 수 있는 도식 후보인가. 처분이 held이고(생성 도중 덱이 바뀐 stale 후보는 같은 탭이 따라갔다면 버렸을 후보다,
// 계획 리뷰 PR-01), 막는 낡음 사유가 없고, 관련 입력 해시(d1:)가 있어 다른 곳의 변경과 입력 변경을 가를 수 있고(W2-a),
// 결과가 형식 검사를 통과한 도식이어야 한다. 실패하면 사용자에게 보일 이유를 돌려준다
export function reopenRefusal(job: JobView): string | null {
  const result = job.result as DiagramGenerationResult | null;
  if (!result || result.status !== "ok" || !result.diagram) return "작성 창에서 불러올 도식이 없는 결과입니다.";
  if (!job.relevance_hash?.startsWith("d1:")) return "이전 버전에서 만든 도식 후보라 지금 입력과 비교할 수 없습니다.";
  if (job.candidate_status !== "held" && job.candidate_status !== "stale") return "이미 처리한 도식 후보입니다.";
  // 입력이 바뀐 이유는 행의 상태 문장이 이미 말하므로 따로 붙이지 않는다(빈 문자열은 막되 이유를 더하지 않는다, W2 리뷰 W2R-09)
  if (job.candidate_status !== "held" || blockingReasons(job).length > 0) return "";
  return null;
}

// 작성 창의 시작값과 후보. 교체는 지금 덱의 도식에서 시작하고 역할과 주장 연결은 생성 요청의 값으로 덮지 않는다(계획 리뷰
// PR-03: 열기 조건이 대상의 연결과 내용이 그대로임을 이미 보장한다). 제목은 작성 폼에서 고친 뒤 생성했을 수 있고 AI가 그 제목을
// 기준으로 만들었으므로 요청의 제목을 쓴다(W2 리뷰 W2R-03). 새 도식은 요청의 제목, 역할, 주장으로 채우고, 그 장 ID를 그사이 다른
// 도식이 쓰면 새 번호를 쓴다. 장 ID는 후보 내용에 들어가지 않는다. 열 수 없으면 null이다
export function reopenDiagram(job: JobView, deck: Deck): { draft: DiagramDraft; candidate: ReopenedDiagram } | null {
  if (job.kind !== "diagram" || reopenRefusal(job) !== null) return null;
  const params = job.params as DiagramParams;
  let draft: DiagramDraft;
  if (params.mode === "replace") {
    try {
      const current = editDiagramDraft(deck, params.chapter_id ?? "");
      draft = { ...current, topic: params.topic ?? current.topic };
    } catch {
      return null;
    }
  } else {
    const fresh = createDiagramDraft(deck);
    const taken = !params.chapter_id || deck.structure.chapters.some((c) => c.id === params.chapter_id);
    draft = { ...fresh, id: taken ? fresh.id : params.chapter_id!, topic: params.topic ?? "",
      storyRole: (params.role ?? "") as StoryRole | "", claimIds: [...(params.claim_ids ?? [])] };
  }
  return { draft, candidate: { jobId: job.id, result: job.result as DiagramGenerationResult,
    instructions: params.instructions ?? "" } };
}
