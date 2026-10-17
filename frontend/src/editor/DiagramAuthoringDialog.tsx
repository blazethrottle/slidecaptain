import { useEffect, useRef, useState } from "react";
import { api, AiConsentDeclined, ApiError, isStaleStoryPlan, messageOf, savedEtag, type Deck, type DiagramGenerationResult,
  type GenerationUsage, type RenderPlan, type StoryPlan, type DocumentChangePreview, type DocumentChangeBasis } from "../api/client";
import { runJob, settle, staleError } from "../api/jobs";
import { formatUsage } from "../api/usage";
import { Diagnostics } from "../ui/Diagnostics";
import { describeAiOutput, describeFailure } from "../ui/failure";
import { FailureNotice } from "../ui/FailureNotice";
import { Preview } from "./Preview";
import { DiagramDraftBackup } from "./DiagramDraftBackup";
import { StoryPlanRecoveryGuidance } from "../screens/StoryPlanRecoveryGuidance";
import type { ReopenedDiagram } from "./diagramReopen";
import { availableId, diagramCandidate, diagramInputErrors, requiredDiagramAnswers,
  type DiagramDraft, type DiagramEdge, type DiagramNode, type StoryRole } from "./diagramDraft";

const KINDS = { proposal: "제안", fact: "사실", inference: "추정", unknown: "미확인" };
const ROLES = { step: "단계", entity: "대상", decision: "판단", outcome: "결과" };
const RELATIONS = { proposal: "제안", flow: "흐름", reference: "참조" };
const STORY_ROLES: Record<StoryRole, string> = {
  answer: "답변", context: "맥락", evidence: "근거", risk: "위험", action: "행동",
};

function EvidencePicker({ label, evidence, selected, onChange }: {
  label: string; evidence: StoryPlan["evidence"]; selected: string[]; onChange: (ids: string[]) => void;
}) {
  if (!evidence.length) return <p className="hint">등록된 근거가 없습니다.</p>;
  return <details className="diagram-evidence" open={selected.length > 0}>
    <summary>{label} 근거: {selected.length}개 선택</summary>
    {evidence.map(item => <label key={item.id}>
      <span><input type="checkbox" aria-label={`${label} 근거 ${item.id}`} checked={selected.includes(item.id)}
        onChange={e => onChange(e.target.checked ? [...selected, item.id] : selected.filter(id => id !== item.id))} />
        {item.source_id} ({item.locator.line_start}~{item.locator.line_end}행)</span>
      <span className="diagram-excerpt">{item.excerpt}</span>
    </label>)}
  </details>;
}

function draftBackupText(draft: DiagramDraft, plan: StoryPlan | null | undefined): string {
  const evidenceText = (ids: string[]) => ids.length ? ids.map(id => {
    const item = plan?.evidence.find(e => e.id === id);
    return item ? `${id}: ${item.source_id} (${item.locator.line_start}~${item.locator.line_end}행)\n${item.excerpt}` : id;
  }).join("\n") : "선택 없음";
  const nodeName = (id: string) => {
    const index = draft.nodes.findIndex(node => node.id === id);
    return index < 0 ? `찾을 수 없는 항목 (${id})` : `항목 ${index + 1}: ${draft.nodes[index].content}`;
  };
  return [
    `제목: ${draft.topic}`, `분류 라벨: ${draft.eyebrow}`, `부제: ${draft.subtitle}`, `각주: ${draft.footnote}`,
    `보고 역할: ${draft.storyRole ? STORY_ROLES[draft.storyRole] : "선택 없음"}`,
    "연결할 주장:", ...draft.claimIds.map(id => `${id}: ${plan?.claims.find(claim => claim.id === id)?.statement ?? "확인 필요"}`),
    ...draft.nodes.flatMap((node, i) => [
      "", `항목 ${i + 1}: ${node.content}`, `역할: ${ROLES[node.role]}, 내용 구분: ${KINDS[node.kind]}`,
      "조건 또는 확인할 사항:", ...node.caveats, `근거:\n${evidenceText(node.evidence_ids)}`,
    ]),
    ...draft.edges.flatMap((edge, i) => [
      "", `관계 ${i + 1}: ${edge.label}`, `주체: ${nodeName(edge.from_node_id)}`, `대상: ${nodeName(edge.to_node_id)}`,
      `관계 종류: ${RELATIONS[edge.relation]}`, `근거:\n${evidenceText(edge.evidence_ids)}`,
    ]),
  ].join("\n");
}

function GeneratedDiagramReview({ diagram, evidence }: {
  diagram: NonNullable<DiagramGenerationResult["diagram"]>; evidence: StoryPlan["evidence"];
}) {
  const nodeName = (id: string) => diagram.nodes.find(node => node.id === id)?.content ?? id;
  const sources = (ids: string[]) => ids.length ? <ul className="diagram-candidate-evidence">{ids.map(id => {
    const item = evidence.find(entry => entry.id === id);
    return <li key={id}>{item ? <>
      <span>{id}: {item.source_id}, {item.locator.line_start}~{item.locator.line_end}행</span>
      <blockquote>{item.excerpt}</blockquote>
    </> : `${id}: 근거를 확인하지 못했습니다.`}</li>;
  })}</ul> : <p className="hint">연결된 근거가 없습니다.</p>;
  return <section className="diagram-ai-candidate" aria-label="AI 도식 후보 검토">
    <h4>AI 후보 검토</h4>
    <p>형식만 확인한 후보입니다. 관계의 의미, 근거의 현재성과 제출 품질은 미검수이며 배치는 아직 확인하지 않았습니다.</p>
    <h5>항목 {diagram.nodes.length}개</h5>
    <ol>{diagram.nodes.map(node => <li key={node.id}>
      <p><strong>{node.content}</strong></p>
      <p>역할: {ROLES[node.role]}, 내용 구분: {KINDS[node.kind]}</p>
      {node.caveats.length > 0 && <><p>조건 또는 확인할 사항</p><ul>{node.caveats.map((caveat, i) => <li key={i}>{caveat}</li>)}</ul></>}
      {sources(node.evidence_ids)}
    </li>)}</ol>
    <h5>관계 {diagram.edges.length}개</h5>
    <ol>{diagram.edges.map(edge => <li key={edge.id}>
      <p><strong>{edge.label}</strong> ({RELATIONS[edge.relation]})</p>
      <p>{nodeName(edge.from_node_id)} → {nodeName(edge.to_node_id)}</p>
      {sources(edge.evidence_ids)}
    </li>)}</ol>
  </section>;
}

export function DiagramAuthoringDialog({ projectName, deck, initialDraft, onApply, onCancel, blocked = false,
  flushBeforeCheck, onConflict, onBusyChange, pollIntervalMs = 1000, initialCandidate }: {
  projectName: string; deck: Deck; initialDraft: DiagramDraft;
  onApply: (candidate: Deck, base: Deck, chapterId: string, persisted?: boolean) => void; onCancel: () => void;
  blocked?: boolean;
  flushBeforeCheck?: () => Promise<boolean>; onConflict?: (message: string) => void;
  onBusyChange?: (busy: boolean) => void;
  pollIntervalMs?: number;
  // 복구 화면에서 다시 연 AI 후보 (C1 계획 W2-b). 여는 순간 처분을 바꾸지 않는다: 시작값은 edit을 거치지 않는다(edit은
  // 보이던 후보를 버린다). 불러오기는 처분하지 않고 그 후보가 아직 held인지만 확인한다(C2 계획 4.2)
  initialCandidate?: ReopenedDiagram;
}) {
  const [base] = useState(deck);
  const [draft, setDraft] = useState(initialDraft);
  const [checked, setChecked] = useState<{ candidate: Deck; plan: RenderPlan } | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [storyStale, setStoryStale] = useState(false);
  const [checking, setChecking] = useState(false);
  const [instructions, setInstructions] = useState(initialCandidate?.instructions ?? "");
  const [generating, setGenerating] = useState(false);
  const [generationResult, setGenerationResult] = useState<DiagramGenerationResult | null>(initialCandidate?.result ?? null);
  const [generationUsage, setGenerationUsage] = useState<GenerationUsage | null>(null);
  const [generationError, setGenerationError] = useState("");
  const [generationNotice, setGenerationNotice] = useState("");
  const [generationConflict, setGenerationConflict] = useState(false);
  const [aiReplacement,setAiReplacement] = useState(false);
  const [replacement,setReplacement] = useState<{preview:DocumentChangePreview;basis:DocumentChangeBasis}|null>(null);
  const [lossChecks,setLossChecks] = useState<string[]>([]);
  const [applying,setApplying] = useState(false);
  const [loadingCandidate, setLoadingCandidate] = useState(false);  // 다시 연 후보의 상태 확인 응답을 기다리는 중
  const generationLease = useRef<symbol | null>(null);
  const generationJob = useRef<string | null>(initialCandidate?.jobId ?? null);  // 지금 보이는 후보를 만든 작업 (처분)
  // 다시 연 후보의 작업. 이 후보는 불러오기 전에 아직 held인지 확인한다
  const reopenedJob = useRef<string | null>(initialCandidate?.jobId ?? null);
  // 작성 폼에 불러온 후보의 작업. 처분은 불러오기가 아니라 반영과 함께 한다(C2 계획 4.2): 새 도식은 반영하기 전에 처분 응답을
  // 기다리고, 교체 도식은 저장 성공 뒤에 처분한다. 불러온 뒤 반영하지 않고 닫으면 후보는 복구 목록에 남는다
  const loadedJob = useRef<string | null>(null);
  const [generationFollowError, setGenerationFollowError] = useState("");
  const [generationFailure, setGenerationFailure] = useState<unknown>(null);
  const live = useRef(true);
  const serial = useRef(0);
  const currentDeck = useRef(deck);
  currentDeck.current = deck;
  const panel = useRef<HTMLDivElement>(null);
  const titleInput = useRef<HTMLInputElement>(null);
  const loadButton = useRef<HTMLButtonElement>(null);
  const review = useRef<HTMLElement>(null);
  const stale = deck !== base;
  const unavailable = blocked || generationConflict;
  const currentBlocked = useRef(unavailable);
  currentBlocked.current = unavailable;
  const storyPlan = base.structure.story_plan;
  const requiredAnswers = new Set(requiredDiagramAnswers(storyPlan, draft.id).map(claim => claim.id));
  const answerDescription = requiredAnswers.size ? "diagram-answer-requirement" : undefined;
  const evidence = storyPlan?.evidence ?? [];
  const allIds = [...draft.nodes, ...draft.edges].map(item => item.id);

  useEffect(() => {
    live.current = true;
    const before = document.activeElement as HTMLElement | null;
    // 다시 연 후보는 불러오기 버튼에 초점을 둔다. 제목 칸에 두면 첫 입력이 그 후보를 버린다(C1 W2 리뷰 W2R-02)
    if (initialCandidate) loadButton.current?.focus();
    else titleInput.current?.focus();
    return () => { live.current = false; serial.current++; before?.focus(); };
  }, []);

  useEffect(() => {
    if (deck !== base || blocked) {
      serial.current++;
      setGenerationResult(null); setChecked(null);
    }
  }, [deck, base, blocked]);

  useEffect(() => {
    // 좁은 화면에서는 결과가 긴 입력 폼 아래에 있다. 검사 결과로 포커스를 옮겨 바로 확인한다.
    if (checked || errors.length) review.current?.focus();
  }, [checked, errors]);

  useEffect(() => {
    // 오류 뒤의 일반 편집이 새 errors=[]를 만들더라도 입력 포커스를 빼앗지 않는다.
    if (storyStale) review.current?.focus();
  }, [storyStale]);

  // 보이던 후보를 쓰지 않고 지우면 버림으로 처분한다. 복구 목록에 사용자가 버린 후보가 쌓이지 않는다 (리뷰 R9)
  const dropCandidate = () => {
    if (generationJob.current) void settle(projectName, generationJob.current, "dismissed");
    generationJob.current = null;
  };
  const edit = (next: DiagramDraft) => {
    if (applying || loadingCandidate) return;
    dropCandidate();
    serial.current++;
    setDraft(next); setChecked(null); setErrors([]); setChecking(false);
    setReplacement(null);setLossChecks([]);
    setGenerationResult(null); setGenerationError(""); setGenerationNotice(""); setGenerationFailure(null);
  };
  const nodeEdit = (index: number, patch: Partial<DiagramNode>) =>
    edit({ ...draft, nodes: draft.nodes.map((n, i) => i === index ? { ...n, ...patch } : n) });
  const edgeEdit = (index: number, patch: Partial<DiagramEdge>) =>
    edit({ ...draft, edges: draft.edges.map((e, i) => i === index ? { ...e, ...patch } : e) });

  const generate = async () => {
    if (!storyPlan || stale || currentBlocked.current || generationLease.current || checking || applying) return;
    const missing = [!draft.topic.trim() && "도식 제목을 입력해 주세요.",
      !draft.storyRole && "보고 계획 연결 역할을 선택해 주세요.",
      !draft.claimIds.length && "보고 계획에 연결할 주장을 하나 이상 선택해 주세요."].filter(Boolean);
    setGenerationError(""); setGenerationNotice(""); setGenerationResult(null); setGenerationFailure(null);
    if (missing.length) { setGenerationError(missing.join("\n")); return; }
    const requestId = ++serial.current;
    const lease = Symbol("diagram-generation");
    generationLease.current = lease;
    // 입력을 바꾸거나 창을 닫아도 전송된 요청은 계속될 수 있다. 호출을 소유한 finally만 잠금을 푼다.
    const reportBusy = onBusyChange;
    setGenerating(true); setChecked(null); setGenerationUsage(null);
    reportBusy?.(true);
    const current = () => live.current && currentDeck.current === base && !currentBlocked.current;
    try {
      if (flushBeforeCheck) {
        const saved = await flushBeforeCheck();
        if (!current() || requestId !== serial.current) return;
        if (!saved) {
          setGenerationError("기존 편집 내용을 저장하지 못했습니다. 작성 내용을 확인한 뒤 창을 닫고 저장 상태를 확인해 주세요.");
          return;
        }
      }
      // 작업 API로 등록하고 끝날 때까지 조회한다 (D2b-5b). 창을 닫아도 작업은 끝까지 돈다
      const { result, job } = await runJob<DiagramGenerationResult>(projectName, "diagram", {
        chapter_id: draft.id, topic: draft.topic, role: draft.storyRole as StoryRole,
        claim_ids: draft.claimIds, instructions,
        ...(!draft.isNew ? {mode:"replace" as const} : {}),
      }, { intervalMs: pollIntervalMs, onStarted: () => dropCandidate(),
        onError: () => setGenerationFollowError("작업 상태를 확인하지 못했습니다. 계속 확인합니다.") });  // 리뷰 R11
      setGenerationFollowError("");
      // 만드는 동안 기준 저장본이나 자료가 바뀌었으면 종전처럼 오류로 알리고 후보는 버린다
      const stale = staleError(job.stale_reasons);
      if (stale) { void settle(projectName, job.id, "dismissed"); throw stale; }
      if (!current()) return;  // 창을 닫은 뒤 도착한 후보는 복구 목록에 남긴다
      // 생성이 끝난 뒤 다른 곳이 덱을 바꾸면 조회 사유가 도식 관련 입력 해시의 사유일 수 있다(W2-a). 열린 작성 창은 W2 이전처럼
      // 덱 변경으로 보고 412로 멈춘다. 그러지 않으면 막아야 할 후보를 보인다(C1 W2 리뷰 W2R-01). 창이 닫혔으면 이 매핑을 하지
      // 않는다: 복구 화면에서 다시 열 수 있는 후보를 다른 탭의 무관한 저장만으로 버리게 된다(C1 묶음 리뷰 BR-03)
      const deckReasons = ["story_plan_changed", "chapter_changed", "chapter_missing", "deck_changed_elsewhere"];
      if (job.stale_reasons.some((r) => deckReasons.includes(r))) {
        void settle(projectName, job.id, "dismissed");
        throw staleError(["deck_changed"])!;
      }
      setGenerationUsage(result.usage);
      if (requestId !== serial.current) {
        void settle(projectName, job.id, "dismissed");  // 입력을 바꿔 쓰지 않는 후보 (리뷰 R9)
        setGenerationNotice("입력이 변경되어 도착한 AI 후보를 사용하지 않았습니다. 현재 입력으로 다시 생성할 수 있습니다.");
        return;
      }
      generationJob.current = job.id;
      setGenerationResult(result);
    } catch (error) {
      if (!current()) return;
      // 입력 변경 뒤 도착한 412도 현재 저장본이 낡았다는 사실은 유효하다.
      if (error instanceof ApiError && error.status === 412) {
        serial.current++; currentBlocked.current = true;
        setGenerationConflict(true); setGenerationResult(null); setChecked(null);
        setGenerationError(messageOf(error)); onConflict?.(messageOf(error));
      } else if (requestId === serial.current) {
        if (error instanceof AiConsentDeclined) setGenerationNotice("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
        else if (isStaleStoryPlan(error)) setStoryStale(true);
        else setGenerationFailure(error);  // 원인별 안내로 보인다 (D3a-4)
      }
    } finally {
      if (generationLease.current === lease) {
        generationLease.current = null;
        if (live.current) setGenerating(false);
        reportBusy?.(false);
      }
    }
  };

  const check = async () => {
    if (stale || checking || applying || currentBlocked.current || generationLease.current) return;
    const requestId = ++serial.current;
    setChecked(null); setGenerationResult(null);setReplacement(null);setLossChecks([]);
    const missing = diagramInputErrors(draft, storyPlan);
    setErrors(missing);
    if (missing.length) return;
    const candidate = diagramCandidate(base, draft);
    setChecking(true);
    try {
      if (flushBeforeCheck) {
        const saved = await flushBeforeCheck();
        if (requestId !== serial.current || currentDeck.current !== base) return;
        if (!saved) {
          setErrors(["기존 편집 내용을 저장하지 못했습니다. 작성 내용을 확인한 뒤 창을 닫고 저장 상태를 확인해 주세요."]);
          return;
        }
      }
      let checkedCandidate = candidate;
      if (storyPlan) {
        checkedCandidate = await api.reconcileDiagramStory(projectName, {
          deck: candidate, chapter_id: draft.id,
          role: draft.storyRole as StoryRole, claim_ids: draft.claimIds,
        });
        if (requestId !== serial.current || currentDeck.current !== base) return;
        setStoryStale(false);
      }
      const plan = await api.measure(checkedCandidate,projectName);
      if (requestId !== serial.current || currentDeck.current !== base) return;
      if (!plan.slides.some(s => s.chapter_id === draft.id && s.diagram)) {
        setErrors(["도식 미리보기를 확인하지 못했습니다. 다시 확인해 주세요."]);
        return;
      }
      if(aiReplacement) {
        const basis=await api.getDocumentChangeBasis(projectName);
        if(requestId!==serial.current || currentDeck.current!==base || currentBlocked.current)return;
        const preview=await api.previewDocumentChange(projectName,{candidate:checkedCandidate,expected_source_fingerprint:basis.sources_fingerprint},basis.base_etag);
        if(requestId!==serial.current || currentDeck.current!==base || currentBlocked.current)return;
        checkedCandidate=preview.candidate;
        setReplacement({preview,basis});
      }
      setChecked({ candidate: checkedCandidate, plan });
    } catch (error) {
      if (requestId === serial.current && currentDeck.current === base) {
        if (error instanceof ApiError && error.status === 412) {
          currentBlocked.current = true; setGenerationConflict(true);
          onConflict?.(messageOf(error));
        }
        if (isStaleStoryPlan(error)) {
          setStoryStale(true);
          setErrors([]);
        } else setErrors([messageOf(error)]);
      }
    } finally {
      if (requestId === serial.current) setChecking(false);
    }
  };
  const applyReplacement = async () => {
    if(!checked || !replacement || applying || stale || currentBlocked.current || generationLease.current ||
      lossChecks.length!==replacement.preview.losses.length)return;
    const requestId=++serial.current;
    const lease=Symbol("diagram-apply");generationLease.current=lease;
    const reportBusy=onBusyChange;reportBusy?.(true);setApplying(true);setErrors([]);
    try {
      const saved=await api.applyDocumentChange(projectName,{candidate:replacement.preview.candidate,
        expected_source_fingerprint:replacement.basis.sources_fingerprint,
        confirmation_token:replacement.preview.confirmation_token,acknowledged_loss_ids:lossChecks},replacement.basis.base_etag);
      // 서버에 저장된 결과다. 조건과 관계없이 넘기고 받을지는 편집 화면이 판정한다: 여기서 버리면 응답 ETag만 캐시에 남아
      // 다음 자동 저장이 이 반영을 덮는다 (D3c-6 리뷰 G11, D3c-5 리뷰 F1과 같은 모양)
      // 교체 도식은 저장 성공 뒤 처분한다. 처분이 실패해도 교체 대상 해시가 반영 뒤 다시 열기를 막는다(C2 계획 4.2)
      const job=loadedJob.current;loadedJob.current=null;
      if(job)void settle(projectName,job,"applied");
      onApply(saved,base,draft.id,true);
    } catch(error) {
      if(requestId===serial.current && live.current) {
        setErrors([messageOf(error)]);
        if(error instanceof ApiError && error.status===422){setReplacement(null);setLossChecks([]);}
        if(error instanceof ApiError && (error.status===409 || error.status===412)) {
          currentBlocked.current=true;setGenerationConflict(true);
          if(error.status===412)onConflict?.(messageOf(error));
        }
      }
    } finally {
      if(generationLease.current===lease)generationLease.current=null;
      if(live.current)setApplying(false);reportBusy?.(false);
    }
  };
  // 새 도식 반영. 불러온 AI 후보가 있으면 반영하기 전에 처분 응답을 기다린다. 반영 뒤 처분이 실패하면 새 도식의 입력 해시가
  // 반영으로 바뀌지 않아 같은 후보를 다시 열어 한 번 더 넣을 수 있다(C2 계획 4.2, 계획 리뷰 PR-01)
  // 서버 저장본이 이 탭의 마지막 저장과 같은가. 다르면 다른 곳이 저장한 것이다(ProjectView의 묶음 종결 확인과 같은 비교)
  // (C2 W2 리뷰 W2R-01). 확인이 실패하면 unknown이다
  const deckState = async (): Promise<"same" | "moved" | "unknown"> => {
    try {
      const etag = await api.peekDeckEtag(projectName);
      return etag !== null && etag !== savedEtag(projectName) ? "moved" : "same";
    } catch {
      return "unknown";
    }
  };
  const stopForElsewhere = () => {
    currentBlocked.current = true; setGenerationConflict(true);
    const message = "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요.";
    setErrors([message]); onConflict?.(message);
  };
  const applyNew = async (candidate: Deck) => {
    const job = loadedJob.current;
    if (job) {
      const requestId = ++serial.current;
      const lease = Symbol("diagram-settle"); generationLease.current = lease;
      setApplying(true); setErrors([]);
      const current = () => requestId === serial.current && live.current;
      let proceed = false;
      // 처분 전 확인, 처분, 처분 뒤 확인을 한 잠금 안에서 한다. 처분 뒤 확인 동안 적용과 닫기가 살아나면, 닫았을 때 후보는
      // applied인데 덱에는 도식이 없었다 (C2 묶음 리뷰 BR-01)
      try {
        // 확인한 뒤 다른 곳이 저장했으면 처분하지 않는다. 처분부터 하면 후보는 사라지고 자동 저장은 412로 끝나 덱에 도식이
        // 없다(W2R-01). 확인하지 못했어도 처분하지 않는다: 확인 없이 처분하면 같은 결과가 될 수 있다(BR-02)
        const before = await deckState();
        // 처분 뒤 확인(아래)과 같은 꼴로 덱과 막힘을 직접 본다. 요청 번호는 effect가 올리므로, 렌더와 effect 사이에 응답이
        // 오면 요청 번호만으로는 놓친다 (C2 확인 리뷰 FC-01)
        if (!current() || currentDeck.current !== base || currentBlocked.current) return;
        if (before === "moved") { stopForElsewhere(); return; }
        if (before === "unknown") { setErrors(["저장본을 확인하지 못해 반영하지 않았습니다. 다시 눌러 주세요."]); return; }
        try {
          await api.settleCandidate(projectName, job, "applied");
        } catch (error) {
          if (current()) {
            if (error instanceof ApiError && error.status === 409) {
              // 안내는 다시 생성을 권하므로 확인 상태를 지워 적용 버튼을 끈다. 다시 확인하면 폼 내용의 일반 반영이 된다(W2R-03)
              loadedJob.current = null; setChecked(null);
              setErrors(["다른 곳에서 이미 처리한 후보입니다. 현재 입력으로 다시 생성할 수 있습니다."]);
            } else setErrors([`AI 후보 처리를 기록하지 못해 반영하지 않았습니다. 다시 눌러 주세요. ${messageOf(error)}`]);
          }
          return;
        }
        loadedJob.current = null;
        // 처분을 기다리는 동안 덱이 바뀌었으면 넣지 않는다. 후보는 이미 처분했지만 폼의 입력은 남는다
        if (!current() || currentDeck.current !== base || currentBlocked.current) return;
        // 처분을 기다리는 동안 다른 곳이 저장했으면 넣지 않는다. 넣으면 자동 저장이 412로 끝난다(W2R-01 둘째 경로). 후보는
        // 이미 처분했으므로 처분 전 저장본 확인부터 처분 뒤 저장본 확인까지의 틈은 남은 위험으로 기록한다(계획 11절, 확인 리뷰
        // FC-02). 확인하지 못했으면 반영한다: 이미 처분했으므로 막으면 후보만 사라진다
        const after = await deckState();
        if (!current()) return;
        if (after === "moved") { stopForElsewhere(); return; }
        proceed = true;
      } finally {
        if (generationLease.current === lease) generationLease.current = null;
        if (live.current) setApplying(false);
      }
      if (!proceed) return;
    }
    onApply(candidate, base, draft.id);
  };
  const cancel = () => { if (applying) return; live.current = false; serial.current++; onCancel(); };
  const slide = checked?.plan.slides.find(s => s.chapter_id === draft.id);

  // 배경의 덱 undo와 Tab 이동이 작성 중 입력에 간섭하지 않게 한다.
  const onKeyDown = (event: React.KeyboardEvent) => {
    event.stopPropagation();
    if (event.key === "Escape") {
      event.preventDefault();
      if (applying) return;
      if (window.confirm("이 창에서 작성한 변경을 버리고 닫을까요?")) cancel();
    }
    if (event.key !== "Tab") return;
    const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>(
      "button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), summary",
    ) ?? []).filter(el => !el.closest("details:not([open])") || el.tagName === "SUMMARY");
    const target = event.shiftKey ? controls.at(-1) : controls[0];
    if ((event.shiftKey && document.activeElement === controls[0]) ||
        (!event.shiftKey && document.activeElement === controls.at(-1))) {
      event.preventDefault(); target?.focus();
    }
  };

  return <div className="diagram-authoring-overlay" onKeyDown={onKeyDown}>
    <div ref={panel} className="diagram-authoring-dialog" role="dialog" aria-modal="true" aria-labelledby="diagram-authoring-title">
      <header>
        <h2 id="diagram-authoring-title">{draft.isNew ? "도식 작성" : "도식 수정"}</h2>
        <p>내용과 관계를 입력하고 배치를 확인한 뒤 적용하세요. 적용 전에는 기존 덱을 바꾸지 않습니다.</p>
        <p className="hint">현재는 한 줄의 인접한 항목 연결을 지원합니다. 등록된 발췌문을 보여 주며 원문 현재성과 관계의 의미는 별도로 확인해야 합니다.</p>
      </header>
      {stale && <p role="alert">원본 덱이 변경되었습니다. 작성 내용을 확인한 뒤 닫고 다시 열어 주세요. 기존 덱에 덮어쓰지 않습니다.</p>}
      {unavailable && <p role="alert">다른 창의 저장과 충돌했습니다. 작성 내용을 확인한 뒤 닫고 저장 충돌을 먼저 해결해 주세요.</p>}
      <div className="diagram-authoring-columns">
        <section className="diagram-authoring-fields" aria-label="도식 내용 입력" inert={applying || loadingCandidate}>
          <div className="field"><label>도식 제목<input ref={titleInput} value={draft.topic}
            onChange={e => edit({ ...draft, topic: e.target.value })} /></label></div>
          <details><summary>분류 라벨, 부제와 각주</summary>
            {([["eyebrow", "분류 라벨"], ["subtitle", "부제"], ["footnote", "각주"]] as const).map(([key, label]) =>
              <div className="field" key={key}><label>{label}<input value={draft[key]}
                onChange={e => edit({ ...draft, [key]: e.target.value })} /></label></div>)}
          </details>
          {storyPlan && <section className="diagram-story-link" aria-label="보고 계획 연결">
            <h3>보고 계획 연결</h3>
            <p>기존 보고 계획의 주장 중 이 도식이 다루는 내용을 선택하세요. 선택은 장부 연결일 뿐이며 원문 의미와 제출 품질을 검수한 결과가 아닙니다.</p>
            {answerDescription && <p id={answerDescription} className="hint">
              이 도식이 맡은 핵심 답변 중 다른 답변 장에 연결되지 않은 주장이 있습니다.
              ‘답변’ 역할과 ‘답변 연결 유지 필요’로 표시한 주장을 유지해 주세요.
              역할을 바꾸려면 같은 주장을 다루는 다른 답변 장이 먼저 필요합니다.
            </p>}
            <div className="field"><label>도식 장 역할<select aria-label="도식 장 보고 역할"
              aria-describedby={answerDescription} value={draft.storyRole}
              onChange={e => edit({ ...draft, storyRole: e.target.value as StoryRole })}>
              <option value="" disabled={requiredAnswers.size > 0}>선택해 주세요</option>
              {Object.entries(STORY_ROLES).map(([value, label]) => <option key={value} value={value}
                disabled={requiredAnswers.size > 0 && value !== "answer"}>{label}</option>)}
            </select></label></div>
            <fieldset aria-describedby={answerDescription}>
              <legend>연결할 주장</legend>
              {storyPlan.claims.map(claim => <label className="diagram-story-claim" key={claim.id}>
                <input type="checkbox" aria-label={`보고 계획 주장 ${claim.id}`} checked={draft.claimIds.includes(claim.id)}
                  disabled={requiredAnswers.has(claim.id) && draft.claimIds.includes(claim.id)}
                  onChange={e => edit({ ...draft, claimIds: e.target.checked
                    ? [...draft.claimIds, claim.id] : draft.claimIds.filter(id => id !== claim.id) })} />
                [{KINDS[claim.kind]}] {claim.statement}
                {requiredAnswers.has(claim.id) && <span className="hint">답변 연결 유지 필요</span>}
              </label>)}
            </fieldset>
          </section>}
          {storyPlan && <section className="diagram-ai-draft" aria-label="AI 도식 초안">
            <h3>AI 도식 초안</h3>
            <p>위에서 정한 제목, 역할과 주장으로 항목과 관계를 제안받습니다. 후보를 확인하고 작성 폼에 불러온 뒤 배치를 검사하세요.</p>
            {!draft.isNew && <p>기존 도식 교체 후보입니다. 원래 역할·주장과 근거 참조를 유지해야 합니다. 적용 전에 변경 전후를 다시 확인하며 이전 저장본의 스냅샷을 남깁니다.</p>}
            <div className="field"><label>도식 지시사항 (선택)
              <textarea aria-label="AI 도식 지시사항" value={instructions}
                onChange={e => { edit(draft); setInstructions(e.target.value); }} /></label></div>
            <button disabled={generating || checking || applying || stale || unavailable} onClick={() => void generate()}>{draft.isNew ? "AI 도식 초안 생성" : "AI 도식 교체 후보 생성"}</button>
            {generating && <p role="status">AI 후보를 기다리고 있습니다. 입력을 바꾸면 이 후보를 사용하지 않습니다. 창을 닫아도 이미 전송된 요청은 계속될 수 있습니다.</p>}
            {generationFollowError && generating && <p role="status">{generationFollowError}</p>}
            {generationError && <p role="alert">{generationError}</p>}
            <FailureNotice failure={generationFailure ? describeFailure(generationFailure) : null} inModal />
            {generationNotice && <p className="notice">{generationNotice}</p>}
            {generationResult?.status === "format_error" && <FailureNotice failure={describeAiOutput()}>
              <p>AI 응답 원문</p><pre>{generationResult.raw_text}</pre>
              {generationUsage && <p className="usage">{formatUsage(generationUsage)}</p>}
            </FailureNotice>}
            {generationResult?.status === "ok" && generationResult.diagram && !stale && !unavailable && <>
              <GeneratedDiagramReview diagram={generationResult.diagram} evidence={evidence} />
              {generationResult.unverified_numbers.length > 0 && <p className="number-warning">
                등록 근거에서 찾지 못한 수치: {generationResult.unverified_numbers.join(", ")}. 불러오기 전에 확인해 주세요.
              </p>}
              {reopenedJob.current && generationJob.current === reopenedJob.current && (
                <p className="notice" id="reopened-candidate-note">입력을 고치면 이 후보를 버립니다. 먼저 작성 폼에 불러온 뒤 고쳐 주세요.
                  불러온 뒤 반영하지 않고 닫으면 후보는 복구 목록에 남습니다.</p>)}
              <button ref={loadButton} disabled={generating || loadingCandidate}
                aria-describedby={reopenedJob.current && generationJob.current === reopenedJob.current ? "reopened-candidate-note" : undefined}
                onClick={async () => {
                if (!generationResult.diagram || currentDeck.current !== base || currentBlocked.current || generationLease.current) return;
                const job = generationJob.current;
                if (job && job === reopenedJob.current) {
                  // 다시 연 후보는 아직 held인지 확인한다. 다른 탭이 먼저 반영했거나 버렸으면 불러오지 않는다(계획 리뷰 PR-01)
                  setLoadingCandidate(true);
                  let held = false;
                  try {
                    held = (await api.getJob(projectName, job)).candidate_status === "held";
                  } catch (error) {
                    if (!live.current) return;
                    generationJob.current = null; reopenedJob.current = null;
                    setGenerationResult(null);
                    setGenerationNotice(`후보를 불러오지 못했습니다. ${messageOf(error)}`);
                    return;
                  } finally {
                    if (live.current) setLoadingCandidate(false);
                  }
                  if (!live.current) return;
                  if (!held) {
                    generationJob.current = null; reopenedJob.current = null;
                    setGenerationResult(null);
                    setGenerationNotice("다른 곳에서 이미 처리한 후보입니다. 현재 입력으로 다시 생성할 수 있습니다.");
                    return;
                  }
                  // 확인을 기다리는 동안 덱이 바뀌었거나 막혔으면 불러오지 않는다(계획 리뷰 PR-15 ②)
                  if (currentDeck.current !== base || currentBlocked.current) return;
                }
                // 앞서 불러온 다른 후보는 쓰지 않으므로 버린다. 실패하면 복구 목록에 남을 뿐이다(계획 리뷰 PR-15 ①)
                if (loadedJob.current && loadedJob.current !== job) void settle(projectName, loadedJob.current, "dismissed");
                if (job) loadedJob.current = job;
                generationJob.current = null; reopenedJob.current = null;
                edit({ ...draft, nodes: structuredClone(generationResult.diagram.nodes), edges: structuredClone(generationResult.diagram.edges) });
                if(!draft.isNew)setAiReplacement(true);
                setGenerationNotice("AI 후보의 항목과 관계를 작성 폼에 불러왔습니다. 내용과 근거를 확인한 뒤 입력과 배치 확인을 눌러 주세요.");
              }}>작성 폼에 불러오기</button>
            </>}
            {/* 사용량은 접힌 진단 상세에 둔다. 형식 오류면 실패 안내의 진단 상세에 있다 (D3a-4, R12) */}
            {generationUsage && generationResult?.status !== "format_error" && <Diagnostics>
              <p className="usage">{formatUsage(generationUsage)}</p>
              {generationResult?.format_retried && <p>형식 재시도 1회를 거쳤습니다.</p>}
            </Diagnostics>}
          </section>}
          <h3>항목 {draft.nodes.length}개</h3>
          {draft.nodes.map((node, i) => <fieldset className="diagram-item" key={node.id}>
            <legend>항목 {i + 1}</legend>
            <div className="field"><label>내용<textarea aria-label={`항목 ${i + 1} 내용`} value={node.content} maxLength={500}
              onChange={e => nodeEdit(i, { content: e.target.value })} /></label></div>
            <div className="diagram-select-row">
              <label>역할<select aria-label={`항목 ${i + 1} 역할`} value={node.role}
                onChange={e => nodeEdit(i, { role: e.target.value as DiagramNode["role"] })}>
                {Object.entries(ROLES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select></label>
              <label>내용 구분<select aria-label={`항목 ${i + 1} 구분`} value={node.kind}
                onChange={e => nodeEdit(i, { kind: e.target.value as DiagramNode["kind"] })}>
                {Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select></label>
            </div>
            <div className="field"><label>조건 또는 확인할 사항 (한 줄에 하나)
              <textarea aria-label={`항목 ${i + 1} 조건`} value={node.caveats.join("\n")}
                onChange={e => nodeEdit(i, { caveats: e.target.value.split("\n") })} /></label></div>
            <EvidencePicker label={`항목 ${i + 1}`} evidence={evidence} selected={node.evidence_ids}
              onChange={ids => nodeEdit(i, { evidence_ids: ids })} />
            <div className="actions">
              <button aria-label={`항목 ${i + 1} 삭제`} disabled={draft.nodes.length <= 2 ||
                draft.edges.some(e => e.from_node_id === node.id || e.to_node_id === node.id)}
                onClick={() => edit({ ...draft, nodes: draft.nodes.filter(n => n.id !== node.id) })}>항목 삭제</button>
            </div>
          </fieldset>)}
          <button disabled={draft.nodes.length >= 12} onClick={() => edit({ ...draft,
            nodes: [...draft.nodes, { id: availableId("node", allIds), role: "step", kind: "proposal",
              content: "", caveats: [], evidence_ids: [] }] })}>항목 추가</button>
          <p className="hint">항목은 2~12개까지 입력할 수 있습니다. 연결된 항목을 삭제하려면 관계를 먼저 삭제하세요. 내용이 길거나 많으면 배치가 제한될 수 있습니다.</p>
          <h3>관계 {draft.edges.length}개</h3>
          {draft.edges.map((edge, i) => <fieldset className="diagram-item" key={edge.id}>
            <legend>관계 {i + 1}</legend>
            <div className="diagram-select-row">
              {([["from_node_id", "주체"], ["to_node_id", "대상"]] as const).map(([key, label]) =>
                <label key={key}>{label}<select aria-label={`관계 ${i + 1} ${label}`} value={edge[key]}
                  onChange={e => edgeEdit(i, { [key]: e.target.value })}>
                  {draft.nodes.map((n, index) => <option key={n.id} value={n.id}>{index + 1}. {n.content || "내용 없음"}</option>)}
                </select></label>)}
            </div>
            <div className="field"><label>관계 종류<select aria-label={`관계 ${i + 1} 종류`} value={edge.relation}
              onChange={e => edgeEdit(i, { relation: e.target.value as DiagramEdge["relation"] })}>
              {Object.entries(RELATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select></label></div>
            <div className="field"><label>관계 설명<input aria-label={`관계 ${i + 1} 설명`} value={edge.label} maxLength={120}
              onChange={e => edgeEdit(i, { label: e.target.value })} /></label></div>
            <EvidencePicker label={`관계 ${i + 1}`} evidence={evidence} selected={edge.evidence_ids}
              onChange={ids => edgeEdit(i, { evidence_ids: ids })} />
            <button aria-label={`관계 ${i + 1} 삭제`} disabled={draft.edges.length <= 1}
              onClick={() => edit({ ...draft, edges: draft.edges.filter(e => e.id !== edge.id) })}>관계 삭제</button>
          </fieldset>)}
          <button disabled={draft.edges.length >= 24} onClick={() => edit({ ...draft,
            edges: [...draft.edges, { id: availableId("edge", allIds), from_node_id: draft.nodes[0].id,
              to_node_id: draft.nodes[1].id, relation: "proposal", label: "", evidence_ids: [] }] })}>관계 추가</button>
        </section>
        <section ref={review} tabIndex={-1} className={`diagram-authoring-check${storyStale ? " is-recovering" : ""}`} aria-label="도식 배치 확인">
          <h3>적용 전 확인</h3>
          <p>입력을 바꾼 뒤에는 배치를 다시 확인해야 합니다.</p>
          {storyStale && <div role="alert">
            <StoryPlanRecoveryGuidance hasDiagrams={base.structure.chapters.some(chapter => chapter.template === "diagram")} />
            <p>작성 중인 입력은 유지했습니다. 복구 안내를 확인한 뒤 같은 입력으로 다시 확인할 수 있습니다.</p>
          </div>}
          {storyStale && <DiagramDraftBackup text={draftBackupText(draft, storyPlan)} />}
          {errors.length > 0 && <div role="alert"><ul>{errors.map((error, i) => <li key={i}>{error}</li>)}</ul></div>}
          <p role="status">{applying ? "확인한 도식을 저장하고 있습니다. 저장이 끝날 때까지 기다려 주세요." : checking ? "입력과 배치를 확인하고 있습니다." : checked && !stale
            ? "입력과 배치를 확인했습니다. 내용과 제출 품질은 미검수입니다."
            : "아직 현재 입력의 배치를 확인하지 않았습니다."}</p>
          {checked && slide && !stale && <div className="diagram-review-preview"
            style={{ aspectRatio: `${checked.plan.page_width_pt} / ${checked.plan.page_height_pt}` }}>
            <Preview slide={slide} style={checked.plan.style}
            pageW={checked.plan.page_width_pt} pageH={checked.plan.page_height_pt}
            selected={null} onSelect={() => {}} onCommitText={() => {}} />
          </div>}
        </section>
      </div>
      <footer className="actions">
        <button disabled={checking || generating || applying || stale || unavailable} onClick={() => void check()}>입력과 배치 확인</button>
        {replacement && <section aria-label="도식 교체 전후 확인"><h3>도식 교체 변경 확인</h3><p>{replacement.preview.notice}</p>
          {replacement.preview.losses.map(loss=><details key={loss.id} open><summary>{loss.path}</summary>
            <p>변경 전</p><pre>{JSON.stringify(loss.before,null,2)}</pre><p>변경 후</p><pre>{JSON.stringify(loss.after,null,2)}</pre>
            <label><input type="checkbox" checked={lossChecks.includes(loss.id)} disabled={applying} onChange={e=>setLossChecks(v=>e.target.checked?[...v,loss.id]:v.filter(id=>id!==loss.id))} />이 변경을 확인했습니다</label>
          </details>)}
        </section>}
        <button disabled={!checked || stale || checking || generating || applying || unavailable ||
          (aiReplacement && (!replacement || lossChecks.length!==replacement.preview.losses.length))} onClick={() => {
          if(aiReplacement){void applyReplacement();return;}
          if (checked && currentDeck.current === base && !currentBlocked.current && !generationLease.current) void applyNew(checked.candidate);
        }}>도식 적용</button>
        <button disabled={applying} onClick={cancel}>변경 버리고 닫기</button>
      </footer>
    </div>
  </div>;
}
