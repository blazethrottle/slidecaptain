import { useEffect, useRef, useState } from "react";
import { api, AiConsentDeclined, ApiError, isStaleStoryPlan, messageOf, type Deck, type DiagramGenerationResult,
  type GenerationUsage, type RenderPlan, type StoryPlan, type DocumentChangePreview, type DocumentChangeBasis } from "../api/client";
import { runJob, settle, staleError } from "../api/jobs";
import { formatUsage } from "../api/usage";
import { Preview } from "./Preview";
import { DiagramDraftBackup } from "./DiagramDraftBackup";
import { StoryPlanRecoveryGuidance } from "../screens/StoryPlanRecoveryGuidance";
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
  flushBeforeCheck, onConflict, onBusyChange, pollIntervalMs = 1000 }: {
  projectName: string; deck: Deck; initialDraft: DiagramDraft;
  onApply: (candidate: Deck, base: Deck, chapterId: string, persisted?: boolean) => void; onCancel: () => void;
  blocked?: boolean;
  flushBeforeCheck?: () => Promise<boolean>; onConflict?: (message: string) => void;
  onBusyChange?: (busy: boolean) => void;
  pollIntervalMs?: number;
}) {
  const [base] = useState(deck);
  const [draft, setDraft] = useState(initialDraft);
  const [checked, setChecked] = useState<{ candidate: Deck; plan: RenderPlan } | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [storyStale, setStoryStale] = useState(false);
  const [checking, setChecking] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generationResult, setGenerationResult] = useState<DiagramGenerationResult | null>(null);
  const [generationUsage, setGenerationUsage] = useState<GenerationUsage | null>(null);
  const [generationError, setGenerationError] = useState("");
  const [generationNotice, setGenerationNotice] = useState("");
  const [generationConflict, setGenerationConflict] = useState(false);
  const [aiReplacement,setAiReplacement] = useState(false);
  const [replacement,setReplacement] = useState<{preview:DocumentChangePreview;basis:DocumentChangeBasis}|null>(null);
  const [lossChecks,setLossChecks] = useState<string[]>([]);
  const [applying,setApplying] = useState(false);
  const generationLease = useRef<symbol | null>(null);
  const generationJob = useRef<string | null>(null);  // 지금 보이는 후보를 만든 작업 (처분)
  const live = useRef(true);
  const serial = useRef(0);
  const currentDeck = useRef(deck);
  currentDeck.current = deck;
  const panel = useRef<HTMLDivElement>(null);
  const titleInput = useRef<HTMLInputElement>(null);
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
    titleInput.current?.focus();
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

  const edit = (next: DiagramDraft) => {
    if (applying) return;
    serial.current++;
    setDraft(next); setChecked(null); setErrors([]); setChecking(false);
    setReplacement(null);setLossChecks([]);
    setGenerationResult(null); setGenerationError(""); setGenerationNotice("");
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
    setGenerationError(""); setGenerationNotice(""); setGenerationResult(null);
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
      }, { intervalMs: pollIntervalMs });
      // 만드는 동안 기준 저장본이나 자료가 바뀌었으면 종전처럼 오류로 알리고 후보는 버린다
      const stale = staleError("diagram", job.stale_reasons);
      if (stale) { void settle(projectName, job.id, "dismissed"); throw stale; }
      generationJob.current = job.id;
      if (!current()) return;
      setGenerationUsage(result.usage);
      if (requestId !== serial.current) {
        setGenerationNotice("입력이 변경되어 도착한 AI 후보를 사용하지 않았습니다. 현재 입력으로 다시 생성할 수 있습니다.");
        return;
      }
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
        else setGenerationError(messageOf(error));
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
      if(requestId===serial.current && live.current && currentDeck.current===base && !currentBlocked.current)onApply(saved,base,draft.id,true);
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
        <section className="diagram-authoring-fields" aria-label="도식 내용 입력" inert={applying}>
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
            {generationError && <p role="alert">{generationError}</p>}
            {generationNotice && <p className="notice">{generationNotice}</p>}
            {generationResult?.status === "format_error" && <div role="alert">
              <p>AI 응답을 형식에 맞게 읽지 못했습니다. 작성 입력을 유지했습니다. 원문을 확인하고 다시 시도해 주세요.</p>
              <details><summary>AI 응답 원문</summary><pre>{generationResult.raw_text}</pre></details>
            </div>}
            {generationResult && generationResult.format_retried && <p>형식 재시도 1회를 거쳤습니다.</p>}
            {generationResult?.status === "ok" && generationResult.diagram && !stale && !unavailable && <>
              <GeneratedDiagramReview diagram={generationResult.diagram} evidence={evidence} />
              {generationResult.unverified_numbers.length > 0 && <p className="number-warning">
                등록 근거에서 찾지 못한 수치: {generationResult.unverified_numbers.join(", ")}. 불러오기 전에 확인해 주세요.
              </p>}
              <button disabled={generating} onClick={() => {
                if (!generationResult.diagram || currentDeck.current !== base || currentBlocked.current || generationLease.current) return;
                edit({ ...draft, nodes: structuredClone(generationResult.diagram.nodes), edges: structuredClone(generationResult.diagram.edges) });
                // 작성 폼에 불러온 후보는 반영한 것으로 처분한다. 다시 열어도 같은 후보를 권하지 않는다
                if (generationJob.current) void settle(projectName, generationJob.current, "applied");
                if(!draft.isNew)setAiReplacement(true);
                setGenerationNotice("AI 후보의 항목과 관계를 작성 폼에 불러왔습니다. 내용과 근거를 확인한 뒤 입력과 배치 확인을 눌러 주세요.");
              }}>작성 폼에 불러오기</button>
            </>}
            {generationUsage && <p className="usage">{formatUsage(generationUsage)}</p>}
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
          if (checked && currentDeck.current === base && !currentBlocked.current && !generationLease.current) onApply(checked.candidate, base, draft.id);
        }}>도식 적용</button>
        <button disabled={applying} onClick={cancel}>변경 버리고 닫기</button>
      </footer>
    </div>
  </div>;
}
