import { useCallback, useEffect, useRef, useState } from "react";
import { api, messageOf, type ExportHistoryDetail, type ExportHistoryItem, type ExportHistoryPage } from "../api/client";
import { PublishedQualityChecks } from "./ExportQualitySummary";
import { ReviewRecordsPanel, type ReviewLeaveGuard } from "./ReviewRecordsPanel";
import { ExportQualificationPanel } from "./ExportQualificationPanel";

const recordNames = {
  readable: "점검 기록 있음", missing: "점검 기록 없음", invalid: "기록 손상",
  unsupported: "지원하지 않는 기록 형식", unreadable: "점검 기록 읽기 불가",
};
const artifactNames = {
  matched: "PPTX 일치", mismatch: "PPTX 변경 감지", missing: "PPTX 없음",
  unreadable: "PPTX 읽기 불가", unverified: "PPTX 대조 불가",
};
const inputNames = {
  current: "현재 저장본과 일치", stale: "현재 저장본과 다름",
  legacy: "구형 기록: 현재 자료 대조 미지원", unavailable: "현재 저장본 대조 불가",
};
const formatTime = (value: string) => new Date(value).toLocaleString("ko-KR");

function Observation({ item }: { item: ExportHistoryItem }) {
  return <p className="export-history-states">
    <span>{recordNames[item.record_status]}</span>
    <span>{artifactNames[item.artifact_status]}</span>
    <span>{inputNames[item.input_status]}</span>
  </p>;
}

type Props = {
  projectName: string;
  readOnly?: boolean;
  busy?: boolean;
  onScreenReady?: (guard: ReviewLeaveGuard | null) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

export function ExportHistoryPanel(props: Props) {
  // A project switch discards pagination and all outstanding response ownership.
  return <History key={props.projectName} {...props} />;
}

function History({ projectName, readOnly = false, busy = false, onScreenReady, onDirtyChange }: Props) {
  const [page, setPage] = useState<ExportHistoryPage | null>(null);
  const [detail, setDetail] = useState<ExportHistoryDetail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const listRequest = useRef(0);
  const detailRequest = useRef(0);
  const offset = useRef(0);
  const reviewLeave = useRef<ReviewLeaveGuard | null>(null);
  const qualificationLeave = useRef<ReviewLeaveGuard | null>(null);
  const [qualificationBusy, setQualificationBusy] = useState(false);
  const qualificationRequests = useRef(0);
  const dirtyParts = useRef({ manual: false, qualification: false });
  const callbacks = useRef({ onScreenReady, onDirtyChange });
  callbacks.current = { onScreenReady, onDirtyChange };
  const registerReviewLeave = useCallback((guard: ReviewLeaveGuard | null) => { reviewLeave.current = guard; }, []);
  const reportDirty = useCallback((dirty: boolean) => { dirtyParts.current.manual = dirty;
    callbacks.current.onDirtyChange?.(dirty || dirtyParts.current.qualification); }, []);
  const reportQualificationDirty = useCallback((dirty: boolean) => { dirtyParts.current.qualification = dirty;
    callbacks.current.onDirtyChange?.(dirty || dirtyParts.current.manual); }, []);
  const trackQualificationBusy = useCallback((active: boolean) => {
    qualificationRequests.current = Math.max(0, qualificationRequests.current + (active ? 1 : -1));
    setQualificationBusy(qualificationRequests.current > 0);
  }, []);
  const registerQualificationLeave = useCallback((guard: ReviewLeaveGuard | null) => { qualificationLeave.current = guard; }, []);
  const leaveReview = async () => {
    if (qualificationLeave.current && !(await qualificationLeave.current())) return false;
    return reviewLeave.current ? reviewLeave.current() : true;
  };

  const load = async (nextOffset: number, confirmLeave = true) => {
    if (confirmLeave && (busy || qualificationBusy)) return;
    if (confirmLeave && !(await leaveReview())) return;
    const request = ++listRequest.current;
    ++detailRequest.current;
    offset.current = nextOffset;
    setLoading(true); setError(""); setPage(null);
    setDetail(null); setSelected(null); setDetailError(""); setDetailLoading(false);
    try {
      const result = await api.listExports(projectName, nextOffset, 20);
      if (request === listRequest.current) setPage(result);
    } catch (e) {
      if (request === listRequest.current) setError(messageOf(e));
    } finally {
      if (request === listRequest.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load(0, false);
    callbacks.current.onScreenReady?.(leaveReview);
    return () => {
      ++listRequest.current; ++detailRequest.current;
      callbacks.current.onScreenReady?.(null);
      callbacks.current.onDirtyChange?.(false);
    };
    // The keyed component owns one project for its lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const open = async (id: string) => {
    if (busy || qualificationBusy) return;
    if (!(await leaveReview())) return;
    const request = ++detailRequest.current;
    setSelected(id); setDetail(null); setDetailError(""); setDetailLoading(true);
    try {
      const result = await api.getExport(projectName, id);
      if (request === detailRequest.current) setDetail(result);
    } catch (e) {
      if (request === detailRequest.current) setDetailError(messageOf(e));
    } finally {
      if (request === detailRequest.current) setDetailLoading(false);
    }
  };

  return <section className="export-history" aria-label="내보내기 검수 이력">
    <div className="export-history-heading">
      <h2>내보내기 검수 이력</h2>
      <button onClick={() => void load(0)} disabled={busy || loading}>이력 새로고침</button>
    </div>
    <p>저장 당시 점검 기록과 조회 시점의 파일을 확인합니다. 현재 저장본 기준이며, 다른 창이나 앱에서 수정했다면 위의 '이력 새로고침'을 눌러 주세요.</p>
    <p>사전 점검과 수동 기록은 제출 승인을 뜻하지 않습니다. 각 파일의 제출 조건과 독립 검수 결과를 상세에서 확인하세요.</p>
    {loading && <p role="status">이력을 확인하는 중...</p>}
    {error && <p role="alert">{error}</p>}
    {page && <>
      <p className="export-history-meta">조회 시각: {formatTime(page.checked_at)}. 전체 {page.total}개. 파일 수정 시각이 최신인 순서입니다.</p>
      {page.current_input_error && <p role="status">{page.current_input_error}</p>}
      {page.total === 0 ? <p>내보내기 이력이 없습니다.</p> : <>
        {page.items.length === 0 && <p>이 페이지에 남아 있는 이력이 없습니다. 위의 '이력 새로고침'을 눌러 주세요.</p>}
        <ul className="export-history-list">{page.items.map(item => <li key={item.id}>
          <button disabled={busy} aria-label={`${item.id} 상세`} aria-pressed={selected === item.id} onClick={() => void open(item.id)}>{item.id}</button>
          <Observation item={item} />
          <p className="export-history-meta">{item.file_modified_at ? formatTime(item.file_modified_at) : "파일 수정 시각 확인 불가"}</p>
        </li>)}</ul>
        <div className="export-history-pagination">
          <button disabled={busy || page.offset === 0} onClick={() => void load(Math.max(0, offset.current - 20))}>이전 이력</button>
          <span>{page.offset + 1}–{page.offset + page.items.length} / {page.total}</span>
          <button disabled={busy || page.offset + page.limit >= page.total} onClick={() => void load(offset.current + 20)}>다음 이력</button>
        </div>
      </>}
    </>}
    {selected && <section className="export-history-detail" aria-label="내보내기 이력 상세">
      <h3>{selected}</h3>
      {detailLoading && <p role="status">선택한 파일을 다시 대조하는 중...</p>}
      {detailError && <p role="alert">{detailError} <button disabled={busy} onClick={() => void open(selected)}>상세 다시 확인</button></p>}
      {detail && <>
        <p className="export-history-meta">상세 조회 시각: {formatTime(detail.checked_at)}</p>
        <Observation item={detail.item} />
        {detail.current_input_error && <p>{detail.current_input_error}</p>}
        {detail.quality ? <section aria-label="저장 당시 점검 결과">
          <h4>저장 당시 점검 결과</h4>
          <p>아래 결과는 내보냈을 때의 기록입니다. 현재 저장본이나 변경된 PPTX를 다시 검수한 결과가 아닙니다.</p>
          <PublishedQualityChecks quality={detail.quality} />
        </section> : <p>저장 당시 점검 결과를 표시할 수 없습니다. 기존 파일은 그대로 보존됩니다.</p>}
        <ReviewRecordsPanel projectName={projectName} exportId={selected} readOnly={readOnly} busy={busy || qualificationBusy}
          onLeaveReady={registerReviewLeave} onDirtyChange={reportDirty} />
        <ExportQualificationPanel projectName={projectName} exportId={selected} readOnly={readOnly} busy={busy}
          onLeaveReady={registerQualificationLeave} onBusyChange={trackQualificationBusy} onDirtyChange={reportQualificationDirty} />
      </>}
    </section>}
  </section>;
}
