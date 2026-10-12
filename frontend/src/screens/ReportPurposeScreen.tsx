import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, messageOf, type Deck, type ProjectInfo } from "../api/client";
import { BATCH_DISCARD_CONFIRM, BATCH_READ_ONLY_NOTICE } from "../ui/ActiveJobNotice";
import { Button } from "../ui/Button";
import { UnsavedChangeBackup } from "../editor/UnsavedChangeBackup";
import type { SaveStatus } from "../ui/StatusIndicator";

// 보고 목적 단계 (개정판 D3a-2, 계획 4.1). 입력 항목과 저장 계약은 옛 자료 탭의 "보고 정보"와 같다:
// 저장 순간의 최신 덱에 이 화면의 보고 정보만 바꿔 덱 전체를 PUT한다. 입력이 멈추면 자동 저장한다 (D3b-5).
export const REPORT_TYPES = [
  ["weekly", "주간 업무 보고"],
  ["business", "일반 업무 보고"],
  ["monthly", "월간 보고"],
  ["data", "데이터 설명 보고"],
  ["research", "리서치 결과 보고"],
  ["project", "프로젝트 보고"],
  ["results", "결과 보고"],
  ["approval", "승인요청"],
  ["strategy", "전략기획"],
  ["ir", "IR Pitch Deck"],
] as const satisfies ReadonlyArray<readonly [Deck["meta"]["report_type"], string]>;
// 빠진 유형이 있으면 타입 검사가 실패한다. 없는 옵션의 값은 브라우저가 첫 옵션으로 보여 사용자가 보는 유형과
// 저장된 유형이 달라진다 (D3b-1 리뷰 R3)
type MissingReportType = Exclude<Deck["meta"]["report_type"], (typeof REPORT_TYPES)[number][0]>;
const reportTypesComplete: [MissingReportType] extends [never] ? true : never = true;
void reportTypesComplete;

// 보고 정보 4필드만 비교한다: preset_overrides는 이 화면이 건드리지 않는 필드라 비교에 넣으면
// 다른 단계가 남긴 변경과 무관하게 흔들릴 수 있다
function metaEqual(a: Deck["meta"], b: Deck["meta"]): boolean {
  return a.title === b.title && a.report_type === b.report_type
    && a.presenter === b.presenter && a.audience === b.audience
    && !!a.report_type_confirmed === !!b.report_type_confirmed;  // 확인 표시도 저장할 값이다 (D3b-1 리뷰 R4)
}

// 충돌 해소 전 보존의 결과 (D3b-5, 계획 4.5, B9). none은 보존할 미저장 입력이 없다는 뜻이다
export type PurposePreserveResult = { kind: "none" } | { kind: "preserved"; savedAt: string } | { kind: "failed" };

export function ReportPurposeScreen({
  project, deck, onDeckChange, onDirtyChange, onScreenReady, onPreserveReady, onConflict, onSaveStatusChange,
  readOnly = false, readOnlyNotice = false, conflictSignal = 0, onNext, nextDisabled = false, nextTitle,
  saveDelayMs = 1200,
}: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onDirtyChange?: (dirty: boolean) => void;  // 보고 정보가 저장본과 다르면 참 (창 닫기 경고, 묶음 종결 분기)
  // 부모가 단계를 옮기기 전에 플러시하도록. "declined"는 사용자가 머물기를 골랐다는 뜻이다 (D3a-5)
  onScreenReady?: (flush: (() => Promise<boolean | "declined">) | null) => void;
  // 부모가 "서버 내용 다시 읽기" 전에 미저장 보고 정보를 보존하도록 (D3b-5, B9)
  onPreserveReady?: (preserve: (() => Promise<PurposePreserveResult>) | null) => void;
  onConflict?: () => void;  // 저장이 412를 받으면 부모가 충돌 안내를 띄운다
  onSaveStatusChange?: (status: SaveStatus) => void;  // 상단 머리의 저장 상태 (계획 4.1 저장 상태 출처 표)
  // 이 프로젝트의 장 생성 묶음 중(또는 진행 작업 확인 전)에는 보고 정보를 고치지 않는다. readOnlyNotice는 묶음을
  // 확인했을 때만 안내를 보인다 (D3a-5, 계획 4.4)
  readOnly?: boolean;
  readOnlyNotice?: boolean;
  // 부모가 묶음 종결로 충돌 안내를 띄우면 늘린다. 마운트 때 값을 기준으로 비교한다(D3a-β 재리뷰 F1의 함정)
  conflictSignal?: number;
  onNext?: () => void;  // 주 행동 "자료 단계로". 부모의 단계 이동(이탈 플러시 포함)을 거친다 (Q2)
  nextDisabled?: boolean;
  nextTitle?: string;
  saveDelayMs?: number;  // 자동 저장 지연. 편집 화면과 같은 1,200ms (계획 4.5, 사실 10)
}) {
  const [meta, setMeta] = useState(deck.meta);
  const metaRef = useRef(meta);
  metaRef.current = meta;
  // 저장 경로는 최신 덱을 본다. 자동 저장 뒤 부모가 덱을 바꾸므로 닫힌 값으로 보내면 직전 덱 본문이 나간다
  const deckRef = useRef(deck);
  deckRef.current = deck;
  const [saved, setSaved] = useState(deck.meta);  // 마지막으로 서버에 실제 반영된 보고 정보
  const savedRef = useRef(saved);
  const [saving, setSaving] = useState(false);
  const [lastSave, setLastSave] = useState<"ok" | "failed" | "conflict">("ok");
  const [notice, setNotice] = useState("");
  // 충돌(412)이나 묶음 종결 신호를 받으면 "서버 내용 다시 읽기" 전까지 자동 저장을 멈춘다. 응답 직후 이어지는
  // 저장도 막도록 React 상태를 기다리지 않는 ref를 함께 둔다
  const [conflict, setConflict] = useState(false);
  const conflictRef = useRef(false);
  const pausedRef = useRef(readOnly);
  pausedRef.current = readOnly;
  const firstSave = useRef(true);  // 화면을 연 뒤 첫 저장은 스냅샷을 요청한다 (재리뷰 RR2)
  const saveChain = useRef<Promise<boolean>>(Promise.resolve(true));
  const [backup, setBackup] = useState("");  // 보존에 실패한 입력의 복사 상자
  const onDeckChangeRef = useRef(onDeckChange);
  onDeckChangeRef.current = onDeckChange;
  const onConflictRef = useRef(onConflict);
  onConflictRef.current = onConflict;
  const dirty = !metaEqual(meta, saved);

  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    onSaveStatusChange?.({ kind: saving ? "saving" : lastSave === "conflict" ? "conflict"
      : lastSave === "failed" ? "save_failed" : dirty ? "unsaved" : "saved" });
  }, [saving, lastSave, dirty, onSaveStatusChange]);

  const enterConflict = useCallback(() => {
    conflictRef.current = true;
    setConflict(true);
    setLastSave("conflict");
  }, []);
  const seenSignal = useRef(conflictSignal);
  useEffect(() => {
    if (conflictSignal > seenSignal.current) enterConflict();
    seenSignal.current = conflictSignal;
  }, [conflictSignal, enterConflict]);

  const doSave = useCallback(async (target: Deck["meta"]): Promise<boolean> => {
    if (conflictRef.current) return false;
    if (metaEqual(target, savedRef.current)) return true;  // 저장할 것이 없다
    setSaving(true);
    try {
      const updated = { ...deckRef.current, meta: target };
      await api.putDeck(project.name, updated, firstSave.current);
      if (conflictRef.current) return false;  // 다른 경로가 관측한 충돌을 늦은 성공으로 지우지 않는다
      firstSave.current = false;
      savedRef.current = target;
      setSaved(target);
      deckRef.current = updated;
      onDeckChangeRef.current(updated);
      setNotice("");
      setLastSave("ok");
      // 저장하는 동안 이어 친 입력은 이어서 저장한다. 입력을 잠그지 않으므로 이 경로가 없으면 글자가 남지 않는다
      // (리뷰 U1). 그사이 읽기 전용이 됐으면 이어 저장하지 않는다 (리뷰 U2)
      const residual = metaRef.current;
      if (metaEqual(residual, target) || pausedRef.current) return true;
      return await doSave(residual);
    } catch (e) {
      if (e instanceof ApiError && e.status === 412) {
        enterConflict();
        onConflictRef.current?.();
      } else if (!conflictRef.current) {
        setLastSave("failed");
        setNotice(messageOf(e));
      }
      return false;
    } finally {
      setSaving(false);
    }
  }, [project.name, enterConflict]);

  // 저장은 한 줄로 직렬화한다: 겹친 PUT이 역순으로 착지하면 서버가 옛 값을 보유한다
  const saveNow = useCallback((): Promise<boolean> => {
    const next = saveChain.current.then(() => doSave(metaRef.current));
    saveChain.current = next.catch(() => false);
    return next;
  }, [doSave]);
  const saveNowRef = useRef(saveNow);
  saveNowRef.current = saveNow;

  // 자동 저장: 입력이 멈추고 saveDelayMs 뒤. 충돌 중이거나 읽기 전용이면 예약하지 않는다 (리뷰 U2, U3)
  useEffect(() => {
    if (conflict || readOnly || metaEqual(meta, saved)) return;
    const timer = setTimeout(() => void saveNow(), saveDelayMs);
    return () => clearTimeout(timer);
  }, [meta, saved, conflict, readOnly, saveDelayMs, saveNow]);

  // 언마운트 저장: 마지막 입력을 잃지 않는다. 충돌 중이거나 읽기 전용이면 보내지 않는다
  useEffect(() => () => {
    if (!conflictRef.current && !pausedRef.current && !metaEqual(metaRef.current, savedRef.current)) {
      void saveNowRef.current();
    }
  }, []);

  // 떠나기 전 확인. 읽기 전용이면 저장하지 않는다(묶음 중 저장은 묶음의 사슬을 끊는다). 고친 입력이 남았으면 버릴지
  // 묻고, 머물기를 고르면 부모가 실패 안내를 띄우지 않게 "declined"를 돌려준다
  const leaveGuard = useCallback(async (): Promise<boolean | "declined"> => {
    const clean = metaEqual(metaRef.current, savedRef.current);
    if (pausedRef.current && !clean) {
      return window.confirm(BATCH_DISCARD_CONFIRM) ? true : "declined";
    }
    if (conflictRef.current) {
      if (clean) return true;  // 충돌 뒤 입력을 되돌려 남은 변경이 없으면 떠나도 잃는 것이 없다
      onConflictRef.current?.();
      return false;
    }
    return saveNow();
  }, [saveNow]);
  useEffect(() => {
    onScreenReady?.(leaveGuard);
    return () => onScreenReady?.(null);  // 다음 화면이 이 화면의 낡은 플러시를 들고 있지 않게 한다
  }, [onScreenReady, leaveGuard]);

  // 충돌 해소 전 보존 (B9, 리뷰 U4). 보존에 실패하면 복사 상자를 보인다
  const preserve = useCallback(async (): Promise<PurposePreserveResult> => {
    await saveChain.current;
    const unsaved = metaRef.current;
    if (metaEqual(unsaved, savedRef.current)) return { kind: "none" };
    try {
      const info = await api.saveDraft(project.name, {
        reason: "conflict", source: "purpose", deck: { ...deckRef.current, meta: unsaved } });
      setBackup("");
      return { kind: "preserved", savedAt: info.saved_at };
    } catch {
      setBackup(JSON.stringify(unsaved, null, 2));
      return { kind: "failed" };
    }
  }, [project.name]);
  useEffect(() => {
    onPreserveReady?.(preserve);
    return () => onPreserveReady?.(null);
  }, [onPreserveReady, preserve]);

  const retry = () => { setNotice(""); setLastSave("ok"); void saveNow(); };
  // 유형 드롭다운은 초점이 떠날 때 바로 저장한다. 키보드 화살표로 바뀌는 중간 유형은 자동 저장 지연이 묶는다
  const flushOnBlur = () => {
    if (!conflictRef.current && !pausedRef.current && !metaEqual(metaRef.current, savedRef.current)) void saveNow();
  };
  const locked = readOnly;

  return (
    <div className="purpose-screen">
      {notice && (
        <p role="alert">{notice} <Button onClick={retry} disabled={locked || saving}>다시 저장</Button></p>
      )}
      {readOnly && readOnlyNotice && <p role="status">{BATCH_READ_ONLY_NOTICE}</p>}
      {backup && (
        <div role="alert">
          <p>보고 정보를 보존하지 못했습니다. 서버 내용을 다시 읽기 전에 아래 내용을 복사해 보관해 주세요.</p>
          <UnsavedChangeBackup text={backup} label="저장하지 못한 보고 정보" />
        </div>
      )}
      <section>
        <h2>보고 정보</h2>
        <div className="field">
          <label>보고서 제목
            <input aria-label="보고서 제목" value={meta.title} disabled={locked}
              onChange={(e) => setMeta({ ...meta, title: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <label>보고 유형
            <select aria-label="보고 유형" value={meta.report_type} disabled={locked} onBlur={flushOnBlur}
              // 유형을 직접 고르면 확인 표시를 함께 저장한다 (D3b-1 리뷰 R4)
              onChange={(e) => setMeta({ ...meta, report_type: e.target.value as Deck["meta"]["report_type"],
                report_type_confirmed: true })}>
              {REPORT_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>보고자 <span className="hint">(이름 또는 부서. 표지에 표기됩니다)</span>
            <input aria-label="보고자" value={meta.presenter ?? ""} disabled={locked}
              onChange={(e) => setMeta({ ...meta, presenter: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <label>피보고자 <span className="hint">(문서에 적히지 않고, 문체와 상세 수준을 맞추는 데만 씁니다)</span>
            <input aria-label="피보고자" value={meta.audience ?? ""} disabled={locked}
              onChange={(e) => setMeta({ ...meta, audience: e.target.value })} />
          </label>
        </div>
        {/* 주 행동 막대: 화면이 길면 창 아래에 붙어 첫 화면 안에 남는다 (D3a-7 사용자 결정, 계획 6절 배치).
            보고 정보는 자동 저장하므로 주 행동은 다음 단계로 옮기는 것이다 (D3b-5, Q2) */}
        <div className="actions primary-bar">
          <Button variant="primary" onClick={() => onNext?.()} disabled={nextDisabled} title={nextTitle}>자료 단계로</Button>
        </div>
      </section>
    </div>
  );
}
