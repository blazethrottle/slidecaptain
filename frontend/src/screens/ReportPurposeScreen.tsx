import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, messageOf, onProjectEvent, onRemoteProjectEvent, TERMINAL_JOB_STATES, type Deck, type ProjectInfo } from "../api/client";
import { BATCH_DISCARD_CONFIRM, BATCH_READ_ONLY_NOTICE } from "../ui/ActiveJobNotice";
import { Button } from "../ui/Button";
import { UnsavedChangeBackup } from "../editor/UnsavedChangeBackup";
import type { SaveStatus } from "../ui/StatusIndicator";
import {
  DETAIL_MAX, KEY_MESSAGE_MAX, OUTCOME_OTHER_MAX, OUTCOMES, REPORT_DETAIL_FIELDS, REPORT_TYPE_GUIDES, hiddenInputs, isBlank,
  planInputValues, purposeMetaEqual, REPORT_TYPES, typeConfirmed, type DesiredOutcome, type ReportType,
} from "./reportPurpose";
import { ReportTypeExample } from "./ReportTypeExample";

// 보고 목적 단계 (개정판 D3a-2, 계획 4.1). 저장 계약은 옛 자료 탭의 "보고 정보"와 같고, 입력 항목은 D3b-5로 아홉 칸이다
// (서버 PURPOSE_SCREEN_FIELDS): 저장 순간의 최신 덱에 이 화면의 보고 정보만 바꿔 덱 전체를 PUT한다. 입력이 멈추면
// 자동 저장한다 (D3b-5).

// 후보형 작업 (결과를 사용자가 반영하는 작업). 진행 중이면 보고 목적을 고칠 때 결과가 이전 입력 기준이 될 수 있다
const CANDIDATE_KINDS = new Set(["structure", "chapter", "condense", "rewrite", "repair", "diagram"]);

// 충돌 해소 전 보존의 결과 (D3b-5, 계획 4.5, B9). none은 보존할 미저장 입력이 없다는 뜻이다
export type PurposePreserveResult = { kind: "none" } | { kind: "preserved"; savedAt: string } | { kind: "failed" };

export function ReportPurposeScreen({
  project, deck, onDeckChange, onDirtyChange, onScreenReady, onPreserveReady, onConflict, onSaveStatusChange,
  readOnly = false, readOnlyNotice = false, conflictSignal = 0, onNext, nextDisabled = false, nextTitle,
  saveDelayMs = 1200, limitations = [], planStale = false, progressRevision = 0, startInConflict = false,
}: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onDirtyChange?: (dirty: boolean) => void;  // 보고 정보가 저장본과 다르면 참 (창 닫기 경고, 묶음 종결 분기)
  // 부모가 단계를 옮기기 전에 플러시하도록. "declined"는 사용자가 머물기를 골랐다는 뜻이다 (D3a-5)
  onScreenReady?: (flush: (() => Promise<boolean | "declined">) | null) => void;
  // 부모가 "서버 내용 다시 읽기" 전에 미저장 보고 정보를 보존하도록 (D3b-5, B9)
  onPreserveReady?: (preserve: (() => Promise<PurposePreserveResult>) | null) => void;
  // 저장이 412를 받으면 부모가 충돌 안내를 띄운다. 충돌 중 떠나기 시도의 재알림은 renotify로 알려 원인을 바꾸지 않게 한다
  onConflict?: (renotify?: boolean) => void;
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
  limitations?: string[];  // 준비됨에 붙은 사유의 문구(핵심 내용 없음 등). 이 화면의 한계 안내로 보인다 (D3b-1 리뷰 R7)
  // 진행 API가 구성 계획을 낡았다고 판정했다 (D3b-5 리뷰 R6). null은 조회 전이거나 조회에 실패해 모른다는 뜻이다
  planStale?: boolean | null;
  progressRevision?: number;  // 진행 API 응답을 반영한 횟수. 저장 뒤 첫 판정을 기다리는 데 쓴다 (반영 재리뷰 F2)
  // 부모의 충돌 안내가 떠 있는 채로 열렸다. 그 안내가 해소되기 전에는 자동 저장하지 않는다 (D3b-5 리뷰 R3)
  startInConflict?: boolean;
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
  const [lastSave, setLastSave] = useState<"ok" | "failed" | "conflict">(startInConflict ? "conflict" : "ok");
  const [notice, setNotice] = useState("");
  // 충돌(412)이나 묶음 종결 신호를 받으면 "서버 내용 다시 읽기" 전까지 자동 저장을 멈춘다. 응답 직후 이어지는
  // 저장도 막도록 React 상태를 기다리지 않는 ref를 함께 둔다
  const [conflict, setConflict] = useState(startInConflict);
  const conflictRef = useRef(startInConflict);
  const pausedRef = useRef(readOnly);
  pausedRef.current = readOnly;
  const firstSave = useRef(true);  // 화면을 연 뒤 첫 저장은 스냅샷을 요청한다 (재리뷰 RR2)
  const saveChain = useRef<Promise<boolean>>(Promise.resolve(true));
  const [backup, setBackup] = useState("");  // 보존에 실패한 입력의 복사 상자
  const onDeckChangeRef = useRef(onDeckChange);
  onDeckChangeRef.current = onDeckChange;
  const onConflictRef = useRef(onConflict);
  onConflictRef.current = onConflict;
  const dirty = !purposeMetaEqual(meta, saved);
  // 저장된 구성 계획을 낡게 하는 값(서버 계획 지문의 메타 칸과 보고 목적 값)을 고치면 미리 알린다 (계획 4.5, D3b-5 리뷰 R1,
  // R2, R6). 저장 전 입력은 저장본과 비교하고, 저장한 뒤에는 진행 API의 판정(planStale)을 따른다. 화면을 연 때의 값과
  // 비교하면 값을 되돌려 계획이 다시 현재가 돼도 안내가 남았다 (β 묶음 리뷰 B1). 저장이 계획 값을 바꾸면 저장을 시작한
  // 뒤의 진행 API 응답이 올 때까지 판정을 기다리며 안내를 유지한다(안내가 꺼졌다 켜지며 다시 낭독되지 않게 한다). 판정
  // 값의 변화만 기다리면, 이미 낡은 계획에서는 값이 바뀌지 않아 대기가 풀리지 않았다 (반영 재리뷰 F2). 진행 API를 읽지
  // 못하면 지난 판정을 유지한다(F3). 이 화면이 바꾼 값이 아니면 원인을 보고 정보로 단정하지 않는다: 자료나 장 구성만
  // 바뀌어도 진행 API는 같은 사유를 낸다 (B2)
  const [openedValues] = useState(() => planInputValues(deck.meta));
  const [knownStale, setKnownStale] = useState(planStale ?? false);
  useEffect(() => { if (planStale !== null) setKnownStale(planStale); }, [planStale]);
  const revisionRef = useRef(progressRevision);
  revisionRef.current = progressRevision;
  const [pendingSince, setPendingSince] = useState<number | null>(null);
  useEffect(() => {
    if (pendingSince !== null && progressRevision > pendingSince) setPendingSince(null);
  }, [progressRevision, pendingSince]);
  useEffect(() => { if (planStale !== null) setPendingSince(null); }, [planStale]);
  const hasPlan = !!deck.structure.story_plan;
  const planChangedHere = hasPlan && (planInputValues(meta) !== planInputValues(saved) || pendingSince !== null
    // 이 화면에서 저장한 값이 연 때와 다르고 진행 API가 낡았다고 하면, 원인은 이 화면의 변경으로 본다
    || (knownStale && planInputValues(saved) !== openedValues));
  const planStaleElsewhere = hasPlan && !planChangedHere && knownStale;
  // 반영하지 않은 생성 후보나 진행 중인 생성 작업이 있으면 고치기 전에 알린다. 작업이 시작하거나 끝나면 다시 읽는다
  // (리뷰 U21, V19, D3b-5 리뷰 R7)
  const [candidates, setCandidates] = useState<{ held: boolean; running: boolean }>({ held: false, running: false });
  const [jobsRevision, setJobsRevision] = useState(0);
  useEffect(() => {
    const bump = (event: { project: string; kind: string }) => {
      if (event.project === project.name && (event.kind === "job_started" || event.kind === "job_ended")) setJobsRevision((n) => n + 1);
    };
    const offLocal = onProjectEvent(bump);
    const offRemote = onRemoteProjectEvent(bump);
    return () => { offLocal(); offRemote(); };
  }, [project.name]);
  useEffect(() => {
    let live = true;
    api.listJobs(project.name).then((jobs) => {
      if (!live) return;
      const kinds = jobs.filter((job) => CANDIDATE_KINDS.has(job.kind));
      setCandidates({ held: kinds.some((job) => TERMINAL_JOB_STATES.has(job.state) && job.candidate_status === "held"),
        running: kinds.some((job) => !TERMINAL_JOB_STATES.has(job.state)) });
    }).catch(() => {});
    return () => { live = false; };
  }, [project.name, jobsRevision]);

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
    if (purposeMetaEqual(target, savedRef.current)) return true;  // 저장할 것이 없다
    setSaving(true);
    const revisionAtStart = revisionRef.current;
    try {
      const updated = { ...deckRef.current, meta: target };
      await api.putDeck(project.name, updated, firstSave.current);
      if (conflictRef.current) return false;  // 다른 경로가 관측한 충돌을 늦은 성공으로 지우지 않는다
      firstSave.current = false;
      if (planInputValues(target) !== planInputValues(savedRef.current)) setPendingSince(revisionAtStart);
      savedRef.current = target;
      setSaved(target);
      // 착지한 동안 부모 덱이 바뀌었을 수 있으므로 최신 덱에 보고 정보만 얹는다 (D3b-5 리뷰 R8)
      deckRef.current = { ...deckRef.current, meta: target };
      onDeckChangeRef.current(deckRef.current);
      setNotice("");
      setLastSave("ok");
      // 저장하는 동안 이어 친 입력은 이어서 저장한다. 입력을 잠그지 않으므로 이 경로가 없으면 글자가 남지 않는다
      // (리뷰 U1). 그사이 읽기 전용이 됐으면 이어 저장하지 않는다 (리뷰 U2)
      const residual = metaRef.current;
      if (purposeMetaEqual(residual, target) || pausedRef.current) return true;
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
    if (conflict || readOnly || purposeMetaEqual(meta, saved)) return;
    const timer = setTimeout(() => void saveNow(), saveDelayMs);
    return () => clearTimeout(timer);
  }, [meta, saved, conflict, readOnly, saveDelayMs, saveNow]);

  // 언마운트 저장: 마지막 입력을 잃지 않는다. 충돌 중이거나 읽기 전용이면 보내지 않는다
  useEffect(() => () => {
    if (!conflictRef.current && !pausedRef.current && !purposeMetaEqual(metaRef.current, savedRef.current)) {
      void saveNowRef.current();
    }
  }, []);

  // 떠나기 전 확인. 읽기 전용이면 저장하지 않는다(묶음 중 저장은 묶음의 사슬을 끊는다). 고친 입력이 남았으면 버릴지
  // 묻고, 머물기를 고르면 부모가 실패 안내를 띄우지 않게 "declined"를 돌려준다
  const leaveGuard = useCallback(async (): Promise<boolean | "declined"> => {
    const clean = purposeMetaEqual(metaRef.current, savedRef.current);
    if (pausedRef.current && !clean) {
      return window.confirm(BATCH_DISCARD_CONFIRM) ? true : "declined";
    }
    if (conflictRef.current) {
      if (clean) return true;  // 충돌 뒤 입력을 되돌려 남은 변경이 없으면 떠나도 잃는 것이 없다
      onConflictRef.current?.(true);  // 재알림이다. 떠 있는 안내의 원인을 바꾸지 않는다
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
    // 다시 읽기로 이 화면을 버리므로 저장을 멈춘다. 멈추지 않으면 다시 마운트할 때 언마운트 저장이 버린 입력을 보낸다
    // (D3b-5 리뷰 R3)
    conflictRef.current = true;
    await saveChain.current;
    const unsaved = metaRef.current;
    if (purposeMetaEqual(unsaved, savedRef.current)) return { kind: "none" };
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
    if (!conflictRef.current && !pausedRef.current && !purposeMetaEqual(metaRef.current, savedRef.current)) void saveNow();
  };
  const locked = readOnly;
  const confirmed = typeConfirmed(meta);
  const type = meta.report_type;
  const guide = REPORT_TYPE_GUIDES[type];
  const hidden = hiddenInputs(meta);
  const hiddenCount = hidden.details.length + (hidden.other ? 1 : 0);
  const update = (patch: Partial<Deck["meta"]>) => setMeta((current) => ({ ...current, ...patch }));
  const setDetail = (name: string, value: string) =>
    setMeta((current) => ({ ...current, report_details: { ...(current.report_details ?? {}), [`${type}.${name}`]: value } }));
  // 숨은 입력 지우기: 다른 유형의 추가 입력과 기타가 아닐 때의 기타 설명. 생성에 쓰지 않으므로 계획을 낡게 하지 않는다
  const clearHidden = () => setMeta((current) => ({
    ...current,
    report_details: Object.fromEntries(Object.entries(current.report_details ?? {})
      .filter(([key]) => key.startsWith(`${current.report_type}.`))),
    ...(current.desired_outcome !== "other" ? { desired_outcome_other: "" } : {}),
  }));
  const keyLength = (meta.key_message ?? "").length;
  const otherBlank = meta.desired_outcome === "other" && isBlank(meta.desired_outcome_other);  // 서버와 같은 빈 값 판정 (B8)

  return (
    <div className="purpose-screen">
      {notice && (
        <p role="alert">{notice} <Button onClick={retry} disabled={locked || saving}>다시 저장</Button></p>
      )}
      {readOnly && readOnlyNotice && <p role="status">{BATCH_READ_ONLY_NOTICE}</p>}
      {/* 미리 알림은 늘 있는 상태 알림 안에 둔다. 입력 중 나타날 때 한 번 낭독되고 같은 문장을 되풀이하지 않는다 (D3b-5 리뷰 R10) */}
      <div role="status" className="purpose-notices">
        {candidates.running && <p className="notice">진행 중인 AI 생성이 있습니다. 보고 정보를 고치면 그 결과가 이전 입력 기준이 될 수 있습니다.</p>}
        {candidates.held && <p className="notice">반영하지 않은 생성 후보가 있습니다. 보고 정보를 고치면 그 후보가 이전 입력 기준이 될 수 있습니다.</p>}
        {planChangedHere && <p className="notice">보고 정보가 바뀌어 구성 단계의 저장된 계획을 다시 확인해야 합니다.</p>}
        {planStaleElsewhere && <p className="notice">자료, 보고 정보 또는 장 구성이 바뀌어 구성 단계의 저장된 계획을 다시 확인해야 합니다.</p>}
      </div>
      {backup && (
        <div role="alert">
          <p>보고 정보를 보존하지 못했습니다. 서버 내용을 다시 읽기 전에 아래 내용을 복사해 보관해 주세요.</p>
          <UnsavedChangeBackup text={backup} label="저장하지 못한 보고 정보" />
        </div>
      )}
      {limitations.map((text) => <p key={text} className="hint">{text}</p>)}
      <section aria-labelledby="purpose-basic">
        <h2 id="purpose-basic">기본 정보</h2>
        <div className="field">
          <label>보고서 제목
            <input aria-label="보고서 제목" value={meta.title} disabled={locked}
              onChange={(e) => update({ title: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <label>보고자 <span className="hint">(이름 또는 부서. 표지에 표기됩니다)</span>
            <input aria-label="보고자" value={meta.presenter ?? ""} disabled={locked}
              onChange={(e) => update({ presenter: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <label>피보고자 <span className="hint">(문서에 적히지 않고, 문체와 상세 수준을 맞추는 데만 씁니다)</span>
            <input aria-label="피보고자" value={meta.audience ?? ""} disabled={locked}
              onChange={(e) => update({ audience: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <label>이 보고서에서 전달할 핵심 내용
            <textarea aria-describedby="key-message-count" value={meta.key_message ?? ""}
              maxLength={KEY_MESSAGE_MAX} disabled={locked} onChange={(e) => update({ key_message: e.target.value })} />
          </label>
          <p id="key-message-count" className="hint">{keyLength.toLocaleString("ko-KR")} / {KEY_MESSAGE_MAX.toLocaleString("ko-KR")}자</p>
        </div>
      </section>
      <section aria-labelledby="purpose-type" className="purpose-type">
        <h2 id="purpose-type">보고 유형과 구성</h2>
        <div className="purpose-type-layout">
          <div className="purpose-type-inputs">
            <div className="field">
              <label>보고 유형
                <select aria-label="보고 유형" aria-describedby="report-type-guide" value={confirmed ? type : ""}
                  disabled={locked} onBlur={flushOnBlur}
                  // 유형을 직접 고르면 확인 표시를 함께 저장한다 (D3b-1 리뷰 R4)
                  onChange={(e) => update({ report_type: e.target.value as ReportType, report_type_confirmed: true })}>
                  {/* 확인되지 않은 덱은 고르기를 요청한다. 기본 유형 그대로 쓰려는 사용자도 한 번 골라야 확인된다 (리뷰 U10) */}
                  {!confirmed && <option value="" disabled>보고 유형을 고르세요</option>}
                  {REPORT_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                </select>
              </label>
            </div>
            <div id="report-type-guide">
              {confirmed ? (
                <>
                  <p>{guide.summary}</p>
                  <p className="hint">이 유형의 추천 구성</p>
                  <ol className="purpose-composition">{guide.composition.map((part) => <li key={part}>{part}</li>)}</ol>
                </>
              ) : <p className="hint">유형을 고르지 않으면 리서치 결과 보고로 만듭니다.</p>}
            </div>
            {confirmed && REPORT_DETAIL_FIELDS[type].map(([name, label]) => (
              <div className="field" key={`${type}.${name}`}>
                <label>{label} <span className="hint">(선택)</span>
                  <input value={meta.report_details?.[`${type}.${name}`] ?? ""} maxLength={DETAIL_MAX}
                    disabled={locked} onChange={(e) => setDetail(name, e.target.value)} />
                </label>
              </div>
            ))}
            {hiddenCount > 0 && (
              <p className="hint">지금 쓰지 않는 입력 {hiddenCount}개(다른 유형의 추가 입력, 원하는 결과가 기타가 아닐 때의 기타 설명)가
                남아 있습니다. 생성에는 쓰지 않습니다.{" "}
                <Button onClick={() => { if (window.confirm(`쓰지 않는 입력 ${hiddenCount}개를 지울까요?`)) clearHidden(); }}
                  disabled={locked}>쓰지 않는 입력 지우기</Button></p>
            )}
          </div>
          <ReportTypeExample selected={confirmed ? type : null} closed={conflict} />
        </div>
      </section>
      <section aria-labelledby="purpose-outcome">
        <h2 id="purpose-outcome">원하는 결과</h2>
        <fieldset className="purpose-outcomes" disabled={locked}>
          <legend className="visually-hidden">원하는 결과</legend>
          {/* 고르지 않음은 사용자 미선택(None)이다. 한 번 고른 뒤에도 되돌릴 수 있다 (D3b-5 리뷰 R9) */}
          <label>
            <input type="radio" name="desired-outcome" value="" checked={!meta.desired_outcome}
              onChange={() => update({ desired_outcome: null })} /> 고르지 않음 (보고 유형의 구성을 따름)
          </label>
          {OUTCOMES.map(([value, label]) => (
            <label key={value}>
              <input type="radio" name="desired-outcome" value={value} checked={meta.desired_outcome === value}
                onChange={() => update({ desired_outcome: value as DesiredOutcome })} /> {label}
            </label>
          ))}
        </fieldset>
        {meta.desired_outcome === "other" && (
          <div className="field">
            <label>기타 목적 설명
              <textarea aria-describedby={otherBlank ? "outcome-other-count outcome-other-blank" : "outcome-other-count"}
                value={meta.desired_outcome_other ?? ""} maxLength={OUTCOME_OTHER_MAX} disabled={locked}
                onChange={(e) => update({ desired_outcome_other: e.target.value })} />
            </label>
            <p id="outcome-other-count" className="hint">
              {(meta.desired_outcome_other ?? "").length.toLocaleString("ko-KR")} / {OUTCOME_OTHER_MAX.toLocaleString("ko-KR")}자</p>
            {otherBlank && <p id="outcome-other-blank" className="hint">기타 목적의 설명이 비어 있습니다.</p>}
          </div>
        )}
      </section>
      {/* 주 행동 막대: 화면이 길면 창 아래에 붙어 첫 화면 안에 남는다 (D3a-7 사용자 결정, 계획 6절 배치).
          보고 정보는 자동 저장하므로 주 행동은 다음 단계로 옮기는 것이다 (D3b-5, Q2) */}
      <div className="actions primary-bar">
        <Button variant="primary" onClick={() => onNext?.()} disabled={nextDisabled} title={nextTitle}>자료 단계로</Button>
      </div>
    </div>
  );
}
