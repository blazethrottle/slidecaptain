import type { Chapter, Deck, Slide, StoryPlan } from "../api/client";

type DiagramSlots = Extract<Slide["slots"], { template: "diagram" }>;
export type DiagramNode = DiagramSlots["diagram"]["nodes"][number];
export type DiagramEdge = DiagramSlots["diagram"]["edges"][number];
export type StoryRole = Exclude<StoryPlan["chapters"][number]["role"], "cover" | "divider">;
export type DiagramDraft = {
  id: string; isNew: boolean; topic: string; eyebrow: string; subtitle: string; footnote: string;
  nodes: DiagramNode[]; edges: DiagramEdge[]; storyRole: StoryRole | ""; claimIds: string[];
};

export function availableId(prefix: string, used: string[]): string {
  const ids = new Set(used);
  let n = 1;
  while (ids.has(`${prefix}-${n}`)) n++;
  return `${prefix}-${n}`;
}

export function createDiagramDraft(deck: Deck): DiagramDraft {
  return {
    id: availableId("diagram", deck.structure.chapters.map(c => c.id)), isNew: true,
    topic: "", eyebrow: "", subtitle: "", footnote: "",
    storyRole: "", claimIds: [],
    nodes: ["node-1", "node-2"].map(id => ({
      id, role: "step", content: "", kind: "proposal", evidence_ids: [], caveats: [],
    })),
    edges: [{ id: "edge-1", from_node_id: "node-1", to_node_id: "node-2",
      relation: "proposal", label: "", evidence_ids: [] }],
  };
}

export function editDiagramDraft(deck: Deck, id: string): DiagramDraft {
  const chapter = deck.structure.chapters.find(c => c.id === id);
  const slide = deck.slides.find(s => s.chapter_id === id);
  if (chapter?.template !== "diagram" || slide?.slots.template !== "diagram") {
    throw new Error("수정할 도식을 찾을 수 없습니다.");
  }
  const link = deck.structure.story_plan?.chapters.find(item => item.chapter_id === id);
  return structuredClone({ id, isNew: false, topic: chapter.topic,
    eyebrow: slide.eyebrow ?? "", subtitle: slide.subtitle ?? "", footnote: slide.slots.footnote ?? "",
    storyRole: link && !["cover", "divider"].includes(link.role) ? link.role as StoryRole : "",
    claimIds: link?.claim_ids ?? [], nodes: slide.slots.diagram.nodes, edges: slide.slots.diagram.edges });
}

// 대상 장을 바꿔도 다른 답변 장이 맡지 않는 핵심 주장은 이 도식에 남아야 한다.
export function requiredDiagramAnswers(storyPlan: StoryPlan | null | undefined, chapterId: string): StoryPlan["claims"] {
  if (!storyPlan) return [];
  const otherAnswers = new Set(storyPlan.chapters
    .filter(chapter => chapter.chapter_id !== chapterId && chapter.role === "answer")
    .flatMap(chapter => chapter.claim_ids));
  const required = new Set(storyPlan.answer_claim_ids.filter(id => !otherAnswers.has(id)));
  return storyPlan.claims.filter(claim => required.has(claim.id));
}

// 작성 편의를 위한 필수 입력 검사다. 구조/근거 ID/배치의 진본은 기존 백엔드 검사다.
export function diagramInputErrors(draft: DiagramDraft, storyPlan: StoryPlan | null = null): string[] {
  const errors: string[] = [];
  if (!draft.topic.trim()) errors.push("도식 제목을 입력해 주세요.");
  if (storyPlan) {
    if (!draft.storyRole) errors.push("보고 계획 연결 역할을 선택해 주세요.");
    if (draft.claimIds.length === 0) errors.push("보고 계획에 연결할 주장을 하나 이상 선택해 주세요.");
    const knownClaims = new Set(storyPlan.claims.map(claim => claim.id));
    if (draft.claimIds.some(id => !knownClaims.has(id))) errors.push("보고 계획에 없는 주장이 선택되었습니다.");
    const requiredAnswers = requiredDiagramAnswers(storyPlan, draft.id);
    if (requiredAnswers.length && draft.storyRole && draft.storyRole !== "answer") {
      errors.push("다른 답변 장에 연결되지 않은 핵심 답변이 있습니다. 이 도식의 역할을 답변으로 유지해 주세요.");
    }
    requiredAnswers.filter(claim => !draft.claimIds.includes(claim.id)).forEach(claim => {
      errors.push(`핵심 답변의 연결을 유지해 주세요: ${claim.statement}`);
    });
  }
  draft.nodes.forEach((node, i) => {
    const name = `항목 ${i + 1}`;
    if (!node.content.trim()) errors.push(`${name}: 내용을 입력해 주세요.`);
    if (node.kind === "fact" && node.evidence_ids.length === 0) errors.push(`${name}: 사실에는 근거가 필요합니다.`);
    if (["inference", "unknown"].includes(node.kind) && !node.caveats.some(c => c.trim())) {
      errors.push(`${name}: 추정과 미확인에는 조건이나 확인할 사항이 필요합니다.`);
    }
  });
  draft.edges.forEach((edge, i) => {
    const name = `관계 ${i + 1}`;
    if (!edge.label.trim()) errors.push(`${name}: 관계 설명을 입력해 주세요.`);
    if (edge.from_node_id === edge.to_node_id) errors.push(`${name}: 서로 다른 항목을 연결해 주세요.`);
    if (edge.relation !== "proposal" && edge.evidence_ids.length === 0) {
      errors.push(`${name}: 흐름과 참조에는 관계 자체의 근거가 필요합니다.`);
    }
  });
  return errors;
}

export function diagramCandidate(deck: Deck, draft: DiagramDraft): Deck {
  const existing = deck.structure.chapters.find(c => c.id === draft.id);
  if ((draft.isNew && existing) || (!draft.isNew && existing?.template !== "diagram")) {
    throw new Error("도식의 원본이 변경되었습니다.");
  }
  const chapter: Chapter = existing ? { ...existing, topic: draft.topic.trim() } : {
    id: draft.id, topic: draft.topic.trim(), conclusion: "", template: "diagram", source_refs: [],
  };
  const oldSlide = deck.slides.find(s => s.chapter_id === draft.id);
  const slide: Slide = {
    ...oldSlide, chapter_id: draft.id, eyebrow: draft.eyebrow, subtitle: draft.subtitle,
    slots: { template: "diagram", footnote: draft.footnote,
      diagram: { version: "q3a-v1", id: draft.id,
        canvas: { page_size: "preset", reading_profile: "report" }, layout_variant: "flow_horizontal",
        nodes: draft.nodes.map(n => ({ ...n, content: n.content.trim(),
          caveats: n.caveats.map(c => c.trim()).filter(Boolean), evidence_ids: [...n.evidence_ids] })),
        edges: draft.edges.map(e => ({ ...e, label: e.label.trim(), evidence_ids: [...e.evidence_ids] })),
      } },
  };
  return { ...deck, structure: { ...deck.structure,
    chapters: draft.isNew ? [...deck.structure.chapters, chapter]
      : deck.structure.chapters.map(c => c.id === draft.id ? chapter : c) },
    slides: draft.isNew ? [...deck.slides, slide] : deck.slides.map(s => s.chapter_id === draft.id ? slide : s) };
}
