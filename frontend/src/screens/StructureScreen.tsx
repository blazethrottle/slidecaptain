import { useCallback, useEffect, useRef, useState } from "react";
import {
  AiConsentDeclined, api, ApiError, isStaleStoryPlan, messageOf,
  type Chapter, type ChapterResult, type Deck, type GenerationUsage, type ProjectInfo, type StoryPlan, type TemplateName,
} from "../api/client";
import { formatUsage, sumUsage } from "../api/usage";
import { SELECTABLE_TEMPLATES, TEMPLATE_LABELS } from "../editor/labels";
import { StoryPlanView } from "./StoryPlanView";
import { StoryPlanRecoveryGuidance } from "./StoryPlanRecoveryGuidance";
import { StoryRewritePanel } from "./StoryRewritePanel";
import { DocumentChangePanel } from "./DocumentChangePanel";
import { UnsavedChangeBackup } from "../editor/UnsavedChangeBackup";

// 실패한 장은 결과 자체가 없어 usage 합계에서 빠진다: 그 사실을 합계 줄에 밝힌다 (가정 7)
const FAILED_CHAPTER_USAGE_NOTICE =
  "(실패한 장의 사용량은 이 합계에 포함되지 않았습니다. 정확한 기록은 프로젝트 폴더의 ai-usage.jsonl)";

// 취소는 실패가 아니다 (계획서 B3): AI 전송 고지를 취소하면 "취소"로 표시하고 role=alert 배너를
// 띄우지 않는다. 이 문구는 GeneratePanel의 취소 안내와 같다
const AI_CONSENT_CANCELLED_NOTICE = "전송을 취소했습니다. 필요하면 다시 시도해 주세요.";

type Progress = Record<string, "대기" | "생성 중" | "완료" | "실패" | "취소" | "보류">;

function nextChapterId(chapters: Chapter[]): string {
  const max = chapters
    .map((c) => /^c(\d+)$/.exec(c.id))
    .reduce((n, m) => (m ? Math.max(n, Number(m[1])) : n), 0);
  return `c${max + 1}`;
}

export function StructureScreen({ project, deck, onDeckChange, onDone, onBusyChange, onConflict, onScreenReady, onDirtyChange }: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onDone: () => void;
  onBusyChange?: (busy: boolean) => void;  // 승인 중 순차 생성 진행을 부모(ProjectView)에 알려 다른 탭 진입을 막는다
  onConflict?: () => void;  // 승인 루프의 putDeck이 412를 받으면 부모가 배너를 띄운다
  onScreenReady?: (flush: () => Promise<boolean>) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [draft, setDraft] = useState<Chapter[]>(deck.structure.chapters);
  const [storyPlan, setStoryPlan] = useState<StoryPlan | null>(deck.structure.story_plan ?? null);
  const [decisionQuestion, setDecisionQuestion] = useState(deck.structure.story_plan?.brief.decision_question ?? "");
  const [draftGenerated, setDraftGenerated] = useState(false);  // AI 재생성 초안 여부 (결정 15: 승인 시 전면 교체)
  const [targetChapters, setTargetChapters] = useState("");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [rewriteActive, setRewriteActive] = useState(false);
  const [documentActive,setDocumentActive] = useState(false);
  const [documentOpen,setDocumentOpen] = useState(false);
  const rewriteLeave = useRef<()=>Promise<boolean>>(async()=>true);
  const documentLeave = useRef<()=>Promise<boolean>>(async()=>true);
  const dirtyParts = useRef({rewrite:false,document:false,draft:false});
  const parentDirty = useRef(onDirtyChange);parentDirty.current=onDirtyChange;
  const reportDirty = useCallback(()=>{const d=dirtyParts.current;parentDirty.current?.(d.rewrite||d.document||d.draft);},[]);
  const setRewriteDirty = useCallback((dirty:boolean)=>{dirtyParts.current.rewrite=dirty;reportDirty();},[reportDirty]);
  const setDocumentDirty = useCallback((dirty:boolean)=>{dirtyParts.current.document=dirty;reportDirty();},[reportDirty]);
  // 장 구성 초안이 저장본과 다르면 창 닫기 경고에 포함한다 (D2a-2: 종전에는 경고 없이 사라졌다)
  const draftDirty = JSON.stringify(draft) !== JSON.stringify(deck.structure.chapters);
  useEffect(()=>{dirtyParts.current.draft=draftDirty;reportDirty();},[draftDirty,reportDirty]);
  const registerRewrite = useCallback((guard:()=>Promise<boolean>)=>{rewriteLeave.current=guard;},[]);
  const registerDocument = useCallback((guard:()=>Promise<boolean>)=>{documentLeave.current=guard;},[]);
  useEffect(()=>{onScreenReady?.(async()=>await documentLeave.current() && await rewriteLeave.current());},[onScreenReady]);
  const [error, setError] = useState("");
  const [storyStale, setStoryStale] = useState(false);
  const [cancelNotice, setCancelNotice] = useState("");  // AI 전송 취소 안내 (role=alert 아님)
  const [rawText, setRawText] = useState("");
  // 저장하지 못한 생성 결과의 보존 (D2a-2): 보존 안내 또는 보존마저 실패했을 때 복사할 내용
  const [preservedNotice, setPreservedNotice] = useState("");
  const [unsavedBackup, setUnsavedBackup] = useState<string | null>(null);
  const [numbers, setNumbers] = useState<string[]>([]);
  const [progress, setProgress] = useState<Progress>({});
  const [structureUsage, setStructureUsage] = useState<GenerationUsage | null>(null);
  const [chapterUsageSummary, setChapterUsageSummary] = useState<GenerationUsage | null>(null);
  const [chapterUsageCount, setChapterUsageCount] = useState(0);  // 합계에 실제로 실린 장 수
  const [chapterUsageHadUnaccountedFailure, setChapterUsageHadUnaccountedFailure] = useState(false);
  const questionChanged = decisionQuestion.trim() !== (storyPlan?.brief.decision_question ?? "");
  const hasDiagrams = deck.structure.chapters.some(c => c.template === "diagram");
  const preserveUnsaved = async (target: Deck, reason: "conflict" | "generation_unsaved") => {
    try {
      const info = await api.saveDraft(project.name, { reason, source: "structure_approval", deck: target });
      setUnsavedBackup(null);
      setPreservedNotice(reason === "generation_unsaved"
        ? `저장하지 못한 생성 결과를 보존했습니다(${info.saved_at.slice(0, 16).replace("T", " ")}). 스냅샷 복구 화면의 "충돌로 보존한 변경"에서 보거나 복원할 수 있습니다.`
        : `승인하려던 장 구성을 보존했습니다(${info.saved_at.slice(0, 16).replace("T", " ")}). 스냅샷 복구 화면의 "충돌로 보존한 변경"에서 보거나 복원할 수 있습니다.`);
    } catch {
      setPreservedNotice("");
      setUnsavedBackup(JSON.stringify(target, null, 2));
    }
  };
  const showFailure = (error: unknown) => {
    const stale = isStaleStoryPlan(error);
    setStoryStale(stale);
    setError(stale ? "" : messageOf(error));
  };

  const generate = async () => {
    if (hasDiagrams) return;
    setBusy(true);
    onBusyChange?.(true);
    setError("");
    setStoryStale(false);
    setCancelNotice("");
    setRawText("");
    setStructureUsage(null);
    // F1 리뷰 반영: 새 구조안을 받으면 이전 승인 루프의 장 사용량 합계는 더 이상 유효하지 않다
    setChapterUsageSummary(null);
    setChapterUsageCount(0);
    setChapterUsageHadUnaccountedFailure(false);
    try {
      const n = targetChapters.trim() === "" ? undefined : Number(targetChapters);
      const result = await api.generateStructure(project.name, {
        target_chapters: n, instructions,
        ...(decisionQuestion.trim() ? { brief: {
          decision_question: decisionQuestion.trim(), audience: deck.meta.audience,
          report_type: deck.meta.report_type,
          reading_profile: storyPlan?.brief.reading_profile ?? "미지정",
          constraints: storyPlan?.brief.constraints ?? [],
        } } : {}),
      });
      if (result.status === "format_error") {
        setError(result.format_issue === "answer_not_in_summary"
          ? "AI가 만든 구성에서 핵심 답변을 설명하는 장에 일부 주장이 연결되지 않았습니다. 입력한 자료와 주안점은 유지했습니다. 다시 생성해 주세요."
          : "AI 응답을 형식에 맞게 읽지 못했습니다. 입력한 자료와 주안점은 유지했습니다. 다시 생성해 주세요.");
        setRawText(result.raw_text);
        setStructureUsage(result.usage);  // C-1 리뷰 반영: usage는 상태와 무관하게 항상 채워진다
      } else if (result.structure) {
        setDraft(result.structure.chapters);
        setStoryPlan(result.structure.story_plan ?? null);
        setDraftGenerated(true);
        setNumbers(result.unverified_numbers);
        setStructureUsage(result.usage);
      }
    } catch (e) {
      if (e instanceof AiConsentDeclined) setCancelNotice(AI_CONSENT_CANCELLED_NOTICE);
      else showFailure(e);
    } finally {
      setBusy(false);
      onBusyChange?.(false);
    }
  };

  const update = (i: number, patch: Partial<Chapter>) => {
    setDraft(draft.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  };
  const move = (i: number, delta: number) => {
    const j = i + delta;
    if (j < 0 || j >= draft.length) return;
    const next = [...draft];
    [next[i], next[j]] = [next[j], next[i]];
    setDraft(next);
  };
  const remove = (i: number) => setDraft(draft.filter((_, j) => j !== i));
  const add = () => {
    setDraft([...draft, {
      id: nextChapterId(draft), topic: "새 장", conclusion: "",
      template: "bullet_box", source_refs: [],
    }]);
  };

  const approve = async () => {
    // AI 재생성 초안은 장 id가 재부여되어 옛 슬라이드와의 대응이 보장되지 않으므로 전면 교체한다 (결정 15).
    // 기존 구조안을 손으로 고친 경우에만 id와 템플릿이 일치하는 슬라이드를 계승한다
    const draftById = new Map(draft.map((c) => [c.id, c]));
    const kept = draftGenerated ? [] : deck.slides.filter((s) => {
      const ch = draftById.get(s.chapter_id);
      return ch !== undefined && ch.template === s.slots.template;
    });
    const droppedCount = deck.slides.length - kept.length;
    if (droppedCount > 0) {
      const ok = window.confirm(
        draftGenerated
          ? `새 구조안을 승인하면 기존 장 내용 ${droppedCount}개를 지우고 전부 새로 생성합니다. 계속할까요?`
          : `구조안 변경으로 기존 장 내용 ${droppedCount}개가 사라집니다. 계속할까요?`,
      );
      if (!ok) return;
    }
    setBusy(true);
    onBusyChange?.(true);
    setError("");
    setStoryStale(false);
    setCancelNotice("");
    setPreservedNotice("");
    setUnsavedBackup(null);
    // 이번 승인 루프에서 실제로 결과를 받은 장의 usage만 모은다(가정 7): 결과 자체가 없는
    // 실패(hadUnaccountedFailure)는 usage가 없어 합계에서 자연히 빠지고, 화면이 그 사실을 밝힌다
    const chapterUsages: GenerationUsage[] = [];
    let hadUnaccountedFailure = false;
    try {
      let current: Deck = {
        ...deck, structure: { ...deck.structure, chapters: draft, story_plan: storyPlan }, slides: kept,
      };
      try {
        await api.putDeck(project.name, current, true);  // 승인 반영: 직전 상태가 스냅샷으로 남는다
      } catch (e) {
        if (e instanceof ApiError && e.status === 412) await preserveUnsaved(current, "conflict");
        throw e;
      }
      onDeckChange(current);
      setDraftGenerated(false);  // 승인이 반영된 순간부터는 재승인이 성공분을 계승한다 (실패한 장만 재생성)
      const targets = draft.filter((c) => !current.slides.some((s) => s.chapter_id === c.id));
      setProgress(Object.fromEntries(targets.map((c) => [c.id, "대기"])));
      let failed = false;
      // 승인 루프에서 한 번 취소하면 이 지역 플래그로 남은 장은 관문(ensureConsent)을 다시 묻지
      // 않고 즉시 취소로 표시한다: generateChapter 자체를 부르지 않아야 대화 상자가 장마다
      // 반복되지 않는다 (계획서 B3, 1차 리뷰)
      let cancelledLoop = false;
      for (const chapter of targets) {
        if (cancelledLoop) {
          setProgress((p) => ({ ...p, [chapter.id]: "취소" }));
          continue;
        }
        setProgress((p) => ({ ...p, [chapter.id]: "생성 중" }));
        let result: ChapterResult;
        try {
          result = await api.generateChapter(project.name, chapter.id);
        } catch (e) {
          if (e instanceof AiConsentDeclined) {
            cancelledLoop = true;
            setCancelNotice(AI_CONSENT_CANCELLED_NOTICE);
            setProgress((p) => ({ ...p, [chapter.id]: "취소" }));
            failed = true;
            continue;
          }
          showFailure(e);
          setProgress((p) => ({ ...p, [chapter.id]: "실패" }));
          failed = true;
          hadUnaccountedFailure = true;  // 결과 자체가 없어 usage를 얻지 못했다
          if (isStaleStoryPlan(e)) {
            setProgress(p => Object.fromEntries(Object.entries(p).map(([id, state]) =>
              [id, state === "대기" ? "보류" : state])));
            break;  // 같은 계획을 쓰는 다음 장도 진행할 수 없다.
          }
          continue;
        }
        chapterUsages.push(result.usage);  // format_error도 결과가 있으므로 usage를 얻는다
        if (result.status !== "ok" || !result.slots) {
          setError("일부 장의 AI 응답을 형식에 맞게 읽지 못했습니다. 실패한 장만 다시 시도해 주세요.");
          setRawText(result.raw_text);
          setProgress((p) => ({ ...p, [chapter.id]: "실패" }));
          failed = true;
          continue;
        }
        current = { ...current, slides: [...current.slides,
          // 공통 슬롯은 생성이 채우지 않는다. 값은 사용자가 속성 패널에서 넣는다 (DA-4)
          { chapter_id: chapter.id, slots: result.slots, eyebrow: "", subtitle: "" }] };
        try {
          await api.putDeck(project.name, current, false);
        } catch (e) {
          // 이미 AI 비용을 쓴 결과다. 저장하지 못하면 버리지 않고 보존한다 (D2a-2)
          await preserveUnsaved(current, "generation_unsaved");
          if (e instanceof ApiError && e.status === 412) {
            setProgress((p) => ({ ...p, [chapter.id]: "실패" }));
            onConflict?.();
            return;  // 낡은 덱 위에 더 쌓지 않는다: 나머지 장은 시도하지 않는다 (바깥 finally가 busy를 해제한다)
          }
          throw e;  // 그 외 오류는 기존처럼 바깥 catch가 처리한다
        }
        onDeckChange(current);
        setNumbers((n) => [...new Set([...n, ...result.unverified_numbers])]);
        setProgress((p) => ({ ...p, [chapter.id]: "완료" }));
      }
      if (!failed) onDone();
    } catch (e) {
      // 최초 승인 반영(line 101)의 412도 여기로 떨어진다: 아직 어떤 장도 시도하지 않았으므로
      // 별도 장 표시 없이 onConflict만 알린다 (A5b 리뷰 발견 1)
      if (e instanceof ApiError && e.status === 412) onConflict?.();
      showFailure(e);
    } finally {
      setChapterUsageSummary(chapterUsages.length > 0 ? sumUsage(chapterUsages) : null);
      setChapterUsageCount(chapterUsages.length);
      setChapterUsageHadUnaccountedFailure(hadUnaccountedFailure);
      setBusy(false);
      onBusyChange?.(false);
    }
  };

  return (
    <div className="structure-screen">
      <fieldset className="structure-controls" disabled={busy || rewriteActive || documentActive}>
      {error && <p role="alert">{error}</p>}
      {preservedNotice && <p role="status">{preservedNotice}</p>}
      {unsavedBackup && (
        <div role="alert">
          <p>생성 결과를 저장하지 못했고 보존도 하지 못했습니다. 이 화면을 떠나기 전에 아래 내용을 복사해 보관해 주세요.</p>
          <UnsavedChangeBackup text={unsavedBackup} label="저장하지 못한 생성 결과" />
        </div>
      )}
      {storyStale && <div role="alert"><StoryPlanRecoveryGuidance hasDiagrams={hasDiagrams} /></div>}
      {cancelNotice && <p className="notice">{cancelNotice}</p>}
      {rawText && <details><summary>AI 응답 원문</summary><pre>{rawText}</pre></details>}
      {/* C-1 리뷰 반영: draft 유무와 무관하게 렌더한다(형식 오류 안내 근처).
          draft가 비어 있으면 "장 구성" 섹션 자체가 없어 그 안에 두면 최초 생성의
          format_error에서 사용량을 보여줄 자리가 없었다 */}
      {structureUsage && <p className="usage">{formatUsage(structureUsage)}</p>}
      {numbers.length > 0 && (
        <p className="number-warning">자료에서 찾지 못한 수치가 있습니다: {numbers.join(", ")}. 반영 전에 확인해 주세요.</p>
      )}
      <section>
        <h2>구조안</h2>
        <div className="field">
          <label>보고 질문 (선택)
            <input aria-label="보고 질문" value={decisionQuestion} disabled={busy} readOnly={hasDiagrams}
              placeholder="이 보고서로 무엇을 판단해야 하나요?"
              onChange={(e) => setDecisionQuestion(e.target.value)} />
          </label>
          <p>질문을 입력하면 주장별 근거와 전체 보고 흐름을 함께 계획합니다.</p>
        </div>
        <div className="field">
          <label>목표 장수 (비우면 AI가 정함)
            <input aria-label="목표 장수" type="number" min={1} value={targetChapters}
              onChange={(e) => setTargetChapters(e.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>문서의 주안점 및 원하는 결과 입력
            <textarea aria-label="문서의 주안점 및 원하는 결과 입력" rows={5} value={instructions}
              onChange={(e) => setInstructions(e.target.value)} />
          </label>
        </div>
        <div className="actions">
          <button onClick={generate} disabled={busy || hasDiagrams}>
            {draft.length > 0 || rawText ? "다시 생성" : "구조안 생성"}
          </button>
          {draft.length === 0 && !busy && <span> 자료를 먼저 넣고 눌러 주세요.</span>}
          {busy && <span> 진행 중입니다. 잠시 기다려 주세요...</span>}
        </div>
        {hasDiagrams && <div className="notice">
          <p>저장된 도식을 보존하기 위해 전체 구조안 다시 생성은 아직 지원하지 않습니다. 편집 탭에서 ‘도식 수정’으로 내용을 고칠 수 있으며 여기서는 장 순서를 바꿀 수 있습니다.</p>
          {!storyStale && <details><summary>자료나 보고 계획이 달라졌다면</summary>
            <StoryPlanRecoveryGuidance hasDiagrams confirmed={false} />
          </details>}
        </div>}
      </section>
      {storyPlan && <StoryPlanView plan={storyPlan} />}
      {draft.length > 0 && (
        <section>
          <h2>장 구성</h2>
          <div className="structure-table-scroll" role="region" aria-label="장 구성표" tabIndex={0}>
          <table>
            <thead>
              <tr><th>순서</th><th>주제</th><th>결론 한 줄</th><th>템플릿</th><th></th></tr>
            </thead>
            <tbody>
              {draft.map((c, i) => (
                <tr key={c.id}>
                  <td>
                    <button aria-label={`${c.topic} 위로`} onClick={() => move(i, -1)}>위</button>
                    <button aria-label={`${c.topic} 아래로`} onClick={() => move(i, 1)}>아래</button>
                  </td>
                  <td><input aria-label={`${i + 1}번 장 주제`} value={c.topic} readOnly={c.template === "diagram"}
                    onChange={(e) => update(i, { topic: e.target.value })} /></td>
                  <td><input aria-label={`${i + 1}번 장 결론`} value={c.conclusion ?? ""} readOnly={c.template === "diagram"}
                    onChange={(e) => update(i, { conclusion: e.target.value })} /></td>
                  <td>
                    <select aria-label={`${i + 1}번 장 템플릿`} value={c.template}
                      disabled={c.template === "diagram"}
                      onChange={(e) => update(i, { template: e.target.value as TemplateName })}>
                      {SELECTABLE_TEMPLATES.map((v) => (
                        <option key={v} value={v}>{TEMPLATE_LABELS[v]}</option>
                      ))}
                      {c.template === "diagram" && <option value="diagram">{TEMPLATE_LABELS.diagram}</option>}
                    </select>
                  </td>
                  <td>
                    <button aria-label={`${c.topic} 삭제`} disabled={c.template === "diagram"} onClick={() => remove(i)}>삭제</button>
                    {progress[c.id] && <span> {progress[c.id]}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <button onClick={add}>장 추가</button>
          {/* F2 리뷰 반영: 성공한 장이 하나도 없어도(전부 실패) 실패 단서만은 표시한다.
              chapterUsageSummary만 조건으로 두면 성공분이 0건일 때 이 문단 자체가 사라졌다 */}
          {(chapterUsageSummary || chapterUsageHadUnaccountedFailure) && (
            <p className="usage">
              {[
                chapterUsageSummary
                  && `장 생성 ${chapterUsageCount}회: ${formatUsage(chapterUsageSummary).replace(/^AI 사용량: /, "")}`,
                chapterUsageHadUnaccountedFailure && FAILED_CHAPTER_USAGE_NOTICE,
              ].filter(Boolean).join(" ")}
            </p>
          )}
          {questionChanged && <p className="notice">보고 질문이 바뀌었습니다. 구조안을 다시 생성해 주세요.</p>}
          <button onClick={approve} disabled={busy || draft.length === 0 || questionChanged}>승인하고 내용 생성</button>
        </section>
      )}
      </fieldset>
      {deck.structure.story_plan && <StoryRewritePanel projectName={project.name} deck={deck}
        disabled={busy || documentActive || draftGenerated || JSON.stringify(draft) !== JSON.stringify(deck.structure.chapters)}
        onBusyChange={onBusyChange} onActiveChange={setRewriteActive} onConflict={onConflict}
        onScreenReady={registerRewrite} onDirtyChange={setRewriteDirty}
        onApplied={saved => {
          setDraft(saved.structure.chapters); setStoryPlan(saved.structure.story_plan ?? null);
          setDecisionQuestion(saved.structure.story_plan!.brief.decision_question);
          setDraftGenerated(false); setStoryStale(false); setError("");
          setProgress({}); onDeckChange(saved);
        }} />}
      <button aria-expanded={documentOpen} disabled={busy || rewriteActive} onClick={()=>{
        if(!documentOpen){setDocumentOpen(true);return;}
        void documentLeave.current().then(allowed=>{if(allowed){setDocumentOpen(false);documentLeave.current=async()=>true;setDocumentDirty(false);setDocumentActive(false);}});
      }}>문서 전체 변경과 근거 이동</button>
      {documentOpen && <DocumentChangePanel projectName={project.name} deck={deck}
        disabled={busy || rewriteActive || draftGenerated || JSON.stringify(draft)!==JSON.stringify(deck.structure.chapters)}
        onBusyChange={onBusyChange} onActiveChange={setDocumentActive} onConflict={onConflict}
        onScreenReady={registerDocument} onDirtyChange={setDocumentDirty}
        onApplied={saved=>{
          setDraft(saved.structure.chapters);setStoryPlan(saved.structure.story_plan??null);
          setDecisionQuestion(saved.structure.story_plan?.brief.decision_question??"");
          setDraftGenerated(false);setStoryStale(false);setError("");setProgress({});onDeckChange(saved);
        }} />}
    </div>
  );
}
