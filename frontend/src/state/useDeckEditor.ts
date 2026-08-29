import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, messageOf, type Deck, type RenderPlan } from "../api/client";
import { editorReducer } from "./deckStore";

export type SaveState = "저장됨" | "저장 대기" | "저장 중" | "저장 실패";
export type Timings = { measureMs: number; saveMs: number };

const DEFAULT_TIMINGS: Timings = { measureMs: 300, saveMs: 1200 };  // 결정 1, 2

export function useDeckEditor(
  projectName: string,
  initialDeck: Deck,
  onDeckChange: (d: Deck) => void,
  timings: Timings = DEFAULT_TIMINGS,
) {
  const [state, dispatch] = useReducer(editorReducer, {
    past: [], present: initialDeck, future: [],
  });
  const [plan, setPlan] = useState<RenderPlan | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("저장됨");
  const [error, setError] = useState("");
  const firstSave = useRef(true);      // 편집 세션 첫 저장은 스냅샷 (결정 1)
  const snapshotNext = useRef(false);  // AI 반영 등 의미 시점의 다음 저장
  const savedDeck = useRef(initialDeck);
  const deck = state.present;
  const deckRef = useRef(deck);
  deckRef.current = deck;

  const saveNow = useCallback(async (target: Deck): Promise<boolean> => {
    const snapshot = firstSave.current || snapshotNext.current;
    setSaveState("저장 중");
    try {
      await api.putDeck(projectName, target, snapshot);
      firstSave.current = false;
      snapshotNext.current = false;
      savedDeck.current = target;
      setSaveState("저장됨");
      setError("");
      onDeckChange(target);
      return true;
    } catch (e) {
      setSaveState("저장 실패");
      setError(messageOf(e));
      return false;
    }
  }, [projectName, onDeckChange]);

  // 실측: 디바운스 (결정 2)
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      api.measure(deck)
        .then((p) => { if (!cancelled) setPlan(p); })
        .catch((e) => { if (!cancelled) setError(messageOf(e)); });
    }, timings.measureMs);
    return () => { cancelled = true; clearTimeout(t); };
  }, [deck, timings.measureMs]);

  // 자동 저장: 디바운스 (결정 1). 대기 중임을 표시해 "저장됨" 오표시를 막는다
  useEffect(() => {
    if (deck === savedDeck.current) return;
    setSaveState("저장 대기");
    const t = setTimeout(() => { void saveNow(deck); }, timings.saveMs);
    return () => clearTimeout(t);
  }, [deck, saveNow, timings.saveMs]);

  // 플러시: 보류 중 저장을 즉시 실행한다 (결정 1. 내보내기 직전에 부모가 부른다)
  // 성공 여부를 반환해, 저장 실패 시 내보내기를 중단할 수 있게 한다 (2026-08-29 태스크 16 리뷰 반영)
  const flushSave = useCallback(async (): Promise<boolean> => {
    if (deckRef.current !== savedDeck.current) return saveNow(deckRef.current);
    return true;
  }, [saveNow]);

  // 언마운트 플러시: 탭 전환이나 목록 복귀로 화면이 내려가도 마지막 편집을 잃지 않는다 (결정 1)
  useEffect(() => () => {
    if (deckRef.current !== savedDeck.current) void saveNow(deckRef.current);
  }, [saveNow]);

  const apply = useCallback((edit: (d: Deck) => Deck) => {
    dispatch({ type: "edit", deck: edit(deckRef.current) });
  }, []);

  const replace = useCallback((next: Deck) => {
    snapshotNext.current = true;
    dispatch({ type: "edit", deck: next });
  }, []);

  const undo = useCallback(() => dispatch({ type: "undo" }), []);
  const redo = useCallback(() => dispatch({ type: "redo" }), []);

  return {
    deck, plan, saveState, error,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
    apply, replace, undo, redo, flushSave,
  };
}
