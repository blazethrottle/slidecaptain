import { useState } from "react";
import {
  AiConsentDeclined, api, ApiError, messageOf,
  type Chapter, type ChapterResult, type Deck, type GenerationUsage, type ProjectInfo, type TemplateName,
} from "../api/client";
import { formatUsage, sumUsage } from "../api/usage";
import { TEMPLATE_LABELS } from "../editor/labels";

// 실패한 장은 결과 자체가 없어 usage 합계에서 빠진다: 그 사실을 합계 줄에 밝힌다 (가정 7)
const FAILED_CHAPTER_USAGE_NOTICE =
  "(실패한 장의 사용량은 이 합계에 포함되지 않았습니다. 정확한 기록은 프로젝트 폴더의 ai-usage.jsonl)";

// 취소는 실패가 아니다 (계획서 B3): AI 전송 고지를 취소하면 "취소"로 표시하고 role=alert 배너를
// 띄우지 않는다. 이 문구는 GeneratePanel의 취소 안내와 같다
const AI_CONSENT_CANCELLED_NOTICE = "전송을 취소했습니다. 필요하면 다시 시도해 주세요.";

type Progress = Record<string, "대기" | "생성 중" | "완료" | "실패" | "취소">;

function nextChapterId(chapters: Chapter[]): string {
  const max = chapters
    .map((c) => /^c(\d+)$/.exec(c.id))
    .reduce((n, m) => (m ? Math.max(n, Number(m[1])) : n), 0);
  return `c${max + 1}`;
}

export function StructureScreen({ project, deck, onDeckChange, onDone, onBusyChange, onConflict }: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onDone: () => void;
  onBusyChange?: (busy: boolean) => void;  // 승인 중 순차 생성 진행을 부모(ProjectView)에 알려 다른 탭 진입을 막는다
  onConflict?: () => void;  // 승인 루프의 putDeck이 412를 받으면 부모가 배너를 띄운다
}) {
  const [draft, setDraft] = useState<Chapter[]>(deck.structure.chapters);
  const [draftGenerated, setDraftGenerated] = useState(false);  // AI 재생성 초안 여부 (결정 15: 승인 시 전면 교체)
  const [targetChapters, setTargetChapters] = useState("");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cancelNotice, setCancelNotice] = useState("");  // AI 전송 취소 안내 (role=alert 아님)
  const [rawText, setRawText] = useState("");
  const [numbers, setNumbers] = useState<string[]>([]);
  const [progress, setProgress] = useState<Progress>({});
  const [structureUsage, setStructureUsage] = useState<GenerationUsage | null>(null);
  const [chapterUsageSummary, setChapterUsageSummary] = useState<GenerationUsage | null>(null);
  const [chapterUsageCount, setChapterUsageCount] = useState(0);  // 합계에 실제로 실린 장 수
  const [chapterUsageHadUnaccountedFailure, setChapterUsageHadUnaccountedFailure] = useState(false);

  const generate = async () => {
    setBusy(true);
    onBusyChange?.(true);
    setError("");
    setCancelNotice("");
    setRawText("");
    setStructureUsage(null);
    try {
      const n = targetChapters.trim() === "" ? undefined : Number(targetChapters);
      const result = await api.generateStructure(project.name, {
        target_chapters: n, instructions,
      });
      if (result.status === "format_error") {
        setError("AI 응답을 형식에 맞게 읽지 못했습니다. 원문을 확인하고 다시 생성해 주세요.");
        setRawText(result.raw_text);
      } else if (result.structure) {
        setDraft(result.structure.chapters);
        setDraftGenerated(true);
        setNumbers(result.unverified_numbers);
        setStructureUsage(result.usage);
      }
    } catch (e) {
      if (e instanceof AiConsentDeclined) setCancelNotice(AI_CONSENT_CANCELLED_NOTICE);
      else setError(messageOf(e));
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
    setCancelNotice("");
    // 이번 승인 루프에서 실제로 결과를 받은 장의 usage만 모은다(가정 7): 결과 자체가 없는
    // 실패(hadUnaccountedFailure)는 usage가 없어 합계에서 자연히 빠지고, 화면이 그 사실을 밝힌다
    const chapterUsages: GenerationUsage[] = [];
    let hadUnaccountedFailure = false;
    try {
      let current: Deck = { ...deck, structure: { chapters: draft }, slides: kept };
      await api.putDeck(project.name, current, true);  // 승인 반영: 직전 상태가 스냅샷으로 남는다
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
          setError(messageOf(e));
          setProgress((p) => ({ ...p, [chapter.id]: "실패" }));
          failed = true;
          hadUnaccountedFailure = true;  // 결과 자체가 없어 usage를 얻지 못했다
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
        current = { ...current, slides: [...current.slides, { chapter_id: chapter.id, slots: result.slots }] };
        try {
          await api.putDeck(project.name, current, false);
        } catch (e) {
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
      setError(messageOf(e));
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
      {error && <p role="alert">{error}</p>}
      {cancelNotice && <p className="notice">{cancelNotice}</p>}
      {rawText && <details><summary>AI 응답 원문</summary><pre>{rawText}</pre></details>}
      {numbers.length > 0 && (
        <p className="number-warning">자료에서 찾지 못한 수치가 있습니다: {numbers.join(", ")}. 반영 전에 확인해 주세요.</p>
      )}
      <section>
        <h2>구조안</h2>
        <div className="field">
          <label>목표 장수 (비우면 AI가 정함)
            <input aria-label="목표 장수" type="number" min={1} value={targetChapters}
              onChange={(e) => setTargetChapters(e.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>지시사항
            <textarea aria-label="지시사항" rows={5} value={instructions}
              onChange={(e) => setInstructions(e.target.value)} />
          </label>
        </div>
        <div className="actions">
          <button onClick={generate} disabled={busy}>
            {draft.length > 0 || rawText ? "다시 생성" : "구조안 생성"}
          </button>
          {draft.length === 0 && !busy && <span> 자료를 먼저 넣고 눌러 주세요.</span>}
          {busy && <span> 진행 중입니다. 잠시 기다려 주세요...</span>}
        </div>
      </section>
      {draft.length > 0 && (
        <section>
          <h2>장 구성</h2>
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
                  <td><input aria-label={`${i + 1}번 장 주제`} value={c.topic}
                    onChange={(e) => update(i, { topic: e.target.value })} /></td>
                  <td><input aria-label={`${i + 1}번 장 결론`} value={c.conclusion ?? ""}
                    onChange={(e) => update(i, { conclusion: e.target.value })} /></td>
                  <td>
                    <select aria-label={`${i + 1}번 장 템플릿`} value={c.template}
                      onChange={(e) => update(i, { template: e.target.value as TemplateName })}>
                      {Object.entries(TEMPLATE_LABELS).map(([v, label]) => (
                        <option key={v} value={v}>{label}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button aria-label={`${c.topic} 삭제`} onClick={() => remove(i)}>삭제</button>
                    {progress[c.id] && <span> {progress[c.id]}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button onClick={add}>장 추가</button>
          {structureUsage && <p className="usage">{formatUsage(structureUsage)}</p>}
          {chapterUsageSummary && (
            <p className="usage">
              {`장 생성 ${chapterUsageCount}회: ${formatUsage(chapterUsageSummary).replace(/^AI 사용량: /, "")}`}
              {chapterUsageHadUnaccountedFailure && ` ${FAILED_CHAPTER_USAGE_NOTICE}`}
            </p>
          )}
          <button onClick={approve} disabled={busy || draft.length === 0}>승인하고 내용 생성</button>
        </section>
      )}
    </div>
  );
}
