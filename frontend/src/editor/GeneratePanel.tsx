import { useState } from "react";
import {
  api, messageOf, type ChapterResult, type Deck, type ProjectInfo,
} from "../api/client";

export function GeneratePanel({ project, deck, chapterId, onReplace }: {
  project: ProjectInfo;
  deck: Deck;
  chapterId: string;
  onReplace: (next: Deck) => void;
}) {
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ChapterResult | null>(null);
  const [error, setError] = useState("");
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);

  const run = async (call: () => Promise<ChapterResult>) => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await call());
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };

  const regenerate = () => run(() => api.generateChapter(project.name, chapterId, instructions));
  const condense = () => {
    if (!slide) return;
    void run(() => api.condenseChapter(project.name, chapterId, slide.slots, instructions));
  };

  const applyResult = () => {
    if (!result || result.status !== "ok" || !result.slots) return;
    const slots = result.slots;
    const next: Deck = {
      ...deck,
      slides: deck.slides.some((s) => s.chapter_id === chapterId)
        ? deck.slides.map((s) => (s.chapter_id === chapterId ? { ...s, slots } : s))
        : [...deck.slides, { chapter_id: chapterId, slots }],
    };
    onReplace(next);  // 반영 저장은 스냅샷을 남긴다 (결정 1)
    setResult(null);
  };

  return (
    <section className="generate-panel">
      <h4>AI 다시 쓰기</h4>
      <label>지시사항 (선택)
        <textarea aria-label="재생성 지시사항" value={instructions}
          onChange={(e) => setInstructions(e.target.value)} />
      </label>
      <button onClick={regenerate} disabled={busy}>이 장 다시 생성</button>
      <button onClick={condense} disabled={busy || !slide}>이 장 축약</button>
      {busy && <p>생성 중입니다. 잠시 기다려 주세요 (최대 5분)...</p>}
      {error && <p role="alert">{error}</p>}
      {result && result.status === "format_error" && (
        <div role="alert">
          <p>AI 응답을 형식에 맞게 읽지 못했습니다. 원문을 확인하고 다시 시도해 주세요.</p>
          <details><summary>AI 응답 원문</summary><pre>{result.raw_text}</pre></details>
        </div>
      )}
      {result && result.status === "ok" && (
        <div className="generate-result">
          <p>새 초안이 준비되었습니다.
            {result.condensed && " 분량에 맞춰 축약했습니다."}
            {result.format_retried && " 형식 재시도 1회를 거쳤습니다."}
          </p>
          {result.warnings.length > 0 && (
            <ul>{result.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
          )}
          {result.unverified_numbers.length > 0 && (
            <p className="number-warning">
              자료에서 찾지 못한 수치: {result.unverified_numbers.join(", ")}. 반영 전에 확인해 주세요.
            </p>
          )}
          <button onClick={applyResult}>반영</button>
          <button onClick={() => setResult(null)}>버리기</button>
        </div>
      )}
    </section>
  );
}
