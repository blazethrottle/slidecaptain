import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, ApiError, messageOf, type Deck, type RenderPlan } from "../api/client";
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
  // 계획이 어느 덱을 기준으로 계산됐는지 함께 기억한다. 덱이 바뀐 뒤 새 계획이 오기까지 낡은 계획으로 편집을 열면
  // 다른 불릿을 덮어쓰므로(2026-09-03 저장 안전성 묶음 FC-05), 호출자는 planStale 로 편집을 막는다
  const [planDeck, setPlanDeck] = useState<Deck | null>(null);
  const [measureTick, setMeasureTick] = useState(0);  // 재실측 요청: 디바운스 실측 효과를 다시 돌린다
  const [saveState, setSaveState] = useState<SaveState>("저장됨");
  const [saveError, setSaveError] = useState("");
  // 충돌(412): 다른 창이나 프로그램이 먼저 저장했다. 자동으로 덮어쓰지 않고 자동 저장을 멈춘 채
  // 사용자가 reloadFromServer로 서버 내용을 받아들이길 기다린다 (2026-09-03 저장 안전성 묶음 A5)
  const [conflict, setConflict] = useState(false);
  const conflictRef = useRef(conflict);
  conflictRef.current = conflict;
  // 실측 오류는 저장 오류와 분리한다: 한 상태를 공유하면 뒤이은 저장 성공이 실측 실패 문구를 지웠다 (FC-02)
  const [measureError, setMeasureError] = useState("");
  const firstSave = useRef(true);      // 편집 세션 첫 저장은 스냅샷 (결정 1)
  const snapshotNext = useRef(false);  // AI 반영 등 의미 시점의 다음 저장
  const savedDeck = useRef(initialDeck);
  const deck = state.present;
  const deckRef = useRef(deck);
  deckRef.current = deck;
  // 부모 콜백은 ref 로 들고 있는다: 렌더마다 새 함수를 넘기는 호출자가 있어도 저장 함수와 언마운트 플러시
  // 효과의 식별자가 흔들리지 않는다 (2026-09-03 저장 안전성 묶음 FC-10: 종전에는 저장 중 PUT 이 연사됐다)
  const onDeckChangeRef = useRef(onDeckChange);
  onDeckChangeRef.current = onDeckChange;
  // 저장은 한 줄로 직렬화한다 (FC-04: 겹친 PUT 이 역순으로 착지하면 서버가 구버전을 보유했다)
  const saveChain = useRef<Promise<boolean>>(Promise.resolve(true));
  const inFlight = useRef(0);

  const doPut = useCallback(async (target: Deck): Promise<boolean> => {
    if (target === savedDeck.current) return true;  // 저장할 것이 없다 (되돌리기로 저장본과 같아진 경우 포함)
    const snapshot = firstSave.current || snapshotNext.current;
    inFlight.current += 1;
    setSaveState("저장 중");
    try {
      await api.putDeck(projectName, target, snapshot);
      firstSave.current = false;
      snapshotNext.current = false;
      savedDeck.current = target;
      setSaveError("");
      onDeckChangeRef.current(target);
      const residual = deckRef.current;
      if (residual === target) {
        setSaveState("저장됨");
        return true;
      }
      // 저장이 진행되는 동안 편집이나 되돌리기가 있었다: 그 결과를 이어서 저장한다. 종전에는 이 경로가 없어
      // 되돌린 상태가 서버에 오르지 않고 표시가 '저장 중' 에 멈췄다 (FC-01)
      return doPut(residual);
    } catch (e) {
      if (e instanceof ApiError && e.status === 412) setConflict(true);
      setSaveError(messageOf(e));
      // 실패한 내용을 그 사이에 되돌려 화면이 마지막 저장본과 같아졌으면 서버와 화면이 일치하므로 '저장됨' 이 맞다.
      // 이 경우 덱이 바뀌지 않아 자동 저장 효과가 다시 돌지 않으므로 여기서 표시를 정한다
      setSaveState(deckRef.current === savedDeck.current ? "저장됨" : "저장 실패");
      return false;
    } finally {
      inFlight.current -= 1;
    }
  }, [projectName]);

  const saveNow = useCallback((target: Deck): Promise<boolean> => {
    const next = saveChain.current.then(() => doPut(target));
    saveChain.current = next.catch(() => false);  // doPut 은 던지지 않지만 체인이 실패 상태에 머물지 않게 한다
    return next;
  }, [doPut]);
  const saveNowRef = useRef(saveNow);
  saveNowRef.current = saveNow;

  // 실측: 디바운스 (결정 2). measureTick 은 '다시 그리기' 가 올리며, 별도 호출 경로 대신 이 효과를 재실행한다
  // (cancelled 가드가 늦게 도착한 응답을 걸러 준다)
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      api.measure(deck)
        .then((p) => { if (!cancelled) { setPlan(p); setPlanDeck(deck); setMeasureError(""); } })
        .catch((e) => { if (!cancelled) setMeasureError(messageOf(e)); });
    }, timings.measureMs);
    return () => { cancelled = true; clearTimeout(t); };
  }, [deck, timings.measureMs, measureTick]);

  const remeasure = useCallback(() => setMeasureTick((n) => n + 1), []);

  // 자동 저장: 디바운스 (결정 1). 대기 중임을 표시해 "저장됨" 오표시를 막는다
  useEffect(() => {
    if (deck === savedDeck.current) {
      // 되돌리기로 저장본과 같아졌다. 진행 중 저장이 없으면 표시를 되돌린다 (FC-03).
      // 진행 중 저장이 있으면 그 착지 처리가 잔여 변경을 보고 표시를 정한다
      if (inFlight.current === 0) setSaveState("저장됨");
      return;
    }
    // 충돌 상태에서는 자동 저장을 멈춘다: 사용자가 서버 내용으로 되돌리기 전까지는 다시 시도하지 않는다
    if (conflict) return;
    setSaveState("저장 대기");
    const t = setTimeout(() => { void saveNow(deck); }, timings.saveMs);
    return () => clearTimeout(t);
  }, [deck, saveNow, timings.saveMs, conflict]);

  // 플러시: 진행 중 저장이 끝난 뒤 잔여 편집까지 즉시 저장한다 (결정 1. 내보내기와 화면 이탈 전에 부모가 부른다)
  // 성공 여부를 반환해, 저장 실패 시 내보내기나 이탈을 중단할 수 있게 한다 (2026-08-29 태스크 16 리뷰 반영)
  const flushSave = useCallback(async (): Promise<boolean> => {
    if (conflict) return false;  // 충돌 상태에서는 시도하지 않는다: reloadFromServer로 먼저 해소해야 한다
    await saveChain.current;
    if (deckRef.current !== savedDeck.current) return saveNow(deckRef.current);
    return true;
  }, [saveNow, conflict]);

  // 언마운트 플러시: 탭 전환이나 목록 복귀로 화면이 내려가도 마지막 편집을 잃지 않는다 (결정 1)
  useEffect(() => () => {
    if (!conflictRef.current && deckRef.current !== savedDeck.current) void saveNowRef.current(deckRef.current);
  }, []);

  const apply = useCallback((edit: (d: Deck) => Deck) => {
    dispatch({ type: "edit", deck: edit(deckRef.current) });
  }, []);

  const replace = useCallback((next: Deck) => {
    snapshotNext.current = true;
    dispatch({ type: "edit", deck: next });
  }, []);

  const undo = useCallback(() => dispatch({ type: "undo" }), []);
  const redo = useCallback(() => dispatch({ type: "redo" }), []);

  // 충돌 복구: 서버 덱을 다시 읽어 되돌리기 이력을 비우고, 다음 저장은 스냅샷을 남기며(새 편집 세션),
  // 부모(ProjectView) 의 덱도 함께 갱신한다 (빠지면 다른 탭이 낡은 덱으로 최신본을 덮는다)
  const reloadFromServer = useCallback(async (): Promise<void> => {
    try {
      const serverDeck = await api.getDeck(projectName);
      dispatch({ type: "reset", deck: serverDeck });
      savedDeck.current = serverDeck;
      firstSave.current = true;
      snapshotNext.current = false;
      setSaveError("");
      setConflict(false);
      setSaveState("저장됨");
      onDeckChangeRef.current(serverDeck);
    } catch (e) {
      setSaveError(messageOf(e));
    }
  }, [projectName]);

  const retrySave = flushSave;  // 저장 실패 뒤 재시도 버튼의 별칭

  return {
    deck, plan, saveState, saveError, measureError, conflict,
    planStale: plan !== null && planDeck !== deck,  // 계획이 현재 덱 기준이 아니다: 편집을 열면 안 된다
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
    apply, replace, undo, redo, flushSave, remeasure, reloadFromServer, retrySave,
  };
}
