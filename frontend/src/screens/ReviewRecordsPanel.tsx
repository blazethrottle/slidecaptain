import { useEffect, useRef, useState } from "react";
import { api, messageOf, type ExportReviewRecord, type ExportReviewRequest, type ExportReviews } from "../api/client";

export type ReviewLeaveGuard = () => Promise<boolean>;
type Props = {
  projectName: string;
  exportId: string;
  readOnly?: boolean;
  busy?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  onLeaveReady?: (guard: ReviewLeaveGuard | null) => void;
};
type Category = ExportReviewRequest["category"];
type Form = { category: Category | ""; reviewer: string; note: string; status: ExportReviewRequest["status"] | ""; pages: number[] };
const emptyForm = (): Form => ({ category: "", reviewer: "", note: "", status: "", pages: [] });
const categoryNames: Record<Category, string> = {
  narrative: "보고 흐름", evidence: "근거", representation: "표현", visual: "시각", target_renderer: "목표 PowerPoint 표시",
};
const verdictNames = {
  not_run: "미수행", passed: "통과 (수동 입력)", needs_revision: "수정 필요", stale: "현재 출력에 적용할 수 없음", unavailable: "확인 불가",
};
const currentnessNames = {
  current: "현재 저장본, 자료, 프리셋과 PPTX가 검수 기준에 일치합니다.",
  stale: "현재 저장본, 자료, 프리셋 또는 PPTX가 검수 기준과 다릅니다.",
  unavailable: "검수 기준의 현재성을 확인할 수 없습니다.",
};
const formatTime = (value: string) => new Date(value).toLocaleString("ko-KR");

function RecordDetails({ record }: { record: ExportReviewRecord }) {
  return <>
    <p className="export-history-meta">검수자: {record.reviewer}. 기록 시각: {formatTime(record.reviewed_at)}. 확인한 페이지: {record.pages.join(", ")}</p>
    <p className="review-record-note">{record.note}</p>
  </>;
}

export function ReviewRecordsPanel(props: Props) {
  // 프로젝트/출력이 바뀌면 이전 요청의 응답 소유권과 입력을 함께 분리한다.
  return <Records key={`${props.projectName}/${props.exportId}`} {...props} />;
}

function Records({ projectName, exportId, readOnly = false, busy = false, onDirtyChange, onLeaveReady }: Props) {
  const [basis, setBasis] = useState<ExportReviews | null>(null);
  const [form, setForm] = useState<Form>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [mustReload, setMustReload] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef(0);
  const savingRef = useRef(false);
  const dirty = form.category !== "" || form.reviewer !== "" || form.note !== "" || form.status !== "" || form.pages.length > 0;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const dirtyCallback = useRef(onDirtyChange);
  const leaveCallback = useRef(onLeaveReady);
  dirtyCallback.current = onDirtyChange;
  leaveCallback.current = onLeaveReady;

  const resetForm = () => {
    setForm(emptyForm());
    dirtyRef.current = false;
    dirtyCallback.current?.(false);
  };

  const load = async () => {
    if (savingRef.current) return;
    const owner = ++request.current;
    setLoading(true); setMustReload(true); setError(""); setNotice("");
    try {
      const result = await api.getExportReviews(projectName, exportId);
      if (owner !== request.current) return;
      setBasis(result); setMustReload(false);
    } catch (e) {
      if (owner === request.current) setError(messageOf(e));
    } finally {
      if (owner === request.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    leaveCallback.current?.(async () => {
      // 저장의 결과를 확인하기 전에는 입력을 버리거나 화면을 떠날 수 없다.
      if (savingRef.current) return false;
      if (!dirtyRef.current) return true;
      if (!window.confirm("작성 중인 검수 기록을 저장하지 않고 이동하시겠습니까? 입력한 내용이 사라집니다.")) return false;
      resetForm();
      return true;
    });
    return () => {
      ++request.current;
      leaveCallback.current?.(null);
      dirtyCallback.current?.(false);
    };
    // 키가 고정된 컴포넌트의 수명만 등록한다. 부모 콜백 변경은 dirty 상태를 초기화하지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);

  const slideCount = basis?.slide_count ?? 0;
  const validPages = form.pages.length > 0 && form.pages.every(page => Number.isInteger(page) && page >= 1 && page <= slideCount);
  const fullReview = form.status !== "passed" || form.pages.length === slideCount;
  const canRecord = !readOnly && !!basis?.can_record && basis.status === "current" && !!basis.base_etag && !!basis.input_fingerprint && !!basis.artifact_sha256;
  const canSave = canRecord && !busy && !loading && !saving && !mustReload && !!form.category && !!form.status &&
    !!form.reviewer.trim() && !!form.note.trim() && validPages && fullReview;

  const save = async () => {
    if (!canSave || !basis || !form.category || !form.status || savingRef.current) return;
    const owner = ++request.current;
    savingRef.current = true;
    setSaving(true); setError(""); setNotice("");
    try {
      const result = await api.recordExportReview(projectName, exportId, {
        category: form.category, status: form.status, reviewer: form.reviewer.trim(), note: form.note.trim(),
        pages: [...form.pages].sort((a, b) => a - b),
        expected_input_fingerprint: basis.input_fingerprint!, expected_artifact_sha256: basis.artifact_sha256!,
      }, basis.base_etag!);
      if (owner !== request.current) return;
      setBasis(result); resetForm();
      setNotice("검수 기록을 저장했습니다. 수동 기록은 제출본 승인을 뜻하지 않습니다.");
    } catch (e) {
      if (owner !== request.current) return;
      setError(messageOf(e)); setMustReload(true);
    } finally {
      if (owner === request.current) {
        savingRef.current = false;
        setSaving(false);
      }
    }
  };

  return <section className="review-records" aria-label="수동 검수 기록">
    <div className="export-history-heading">
      <h4>수동 검수 기록</h4>
      <button onClick={() => void load()} disabled={busy || loading || saving}>검수 기준 다시 확인</button>
    </div>
    <p>수동 기록은 검수자의 자기 신고입니다. 독립 검수, 실제 PowerPoint 표시의 자동 확인이나 제출본 승인을 뜻하지 않습니다. 산출물은 검수 전 초안으로 유지됩니다.</p>
    {loading && <p role="status">검수 기준과 기록을 확인하는 중...</p>}
    {saving && <p role="status">검수 기록을 저장하는 중입니다. 저장이 끝날 때까지 이동할 수 없습니다.</p>}
    {busy && <p role="status">초안 내보내기가 끝나면 검수 기록을 입력할 수 있습니다.</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {mustReload && !loading && <p>입력을 보존했습니다. 검수 기준을 다시 확인한 뒤 저장해 주세요.</p>}
    {basis && <>
      <p className="review-currentness">{currentnessNames[basis.status]}</p>
      <p className="export-history-meta">서버 대조 시각: {formatTime(basis.checked_at)}. 확인 대상: {basis.slide_count ?? "미확인"}페이지.</p>
      {basis.reason && <p>{basis.reason}</p>}
      {(basis.storage_status === "invalid" || basis.storage_status === "unreadable") && <p>검수 저장소를 정상적으로 읽지 못했습니다. 기록이 없는 상태로 간주하지 않습니다.</p>}
      <section aria-label="항목별 최근 판정">
        <h5>항목별 최근 판정</h5>
        <ul className="review-category-list">{basis.categories.map(category => {
          const latest = basis.records.find(record => record.id === category.latest_record_id);
          return <li key={category.category}>
            <strong>{categoryNames[category.category]}: {verdictNames[category.status]}</strong>
            {latest && <>
              {(category.status === "stale" || category.status === "unavailable") && <p>과거에 입력한 판정: {verdictNames[latest.status]}</p>}
              <RecordDetails record={latest} />
            </>}
          </li>;
        })}</ul>
      </section>
      <details className="review-history">
        <summary>과거 검수 기록 ({basis.records.length}개)</summary>
        <section aria-label="과거 검수 기록">
          {basis.records.length ? <ol>{basis.records.map(record => <li key={record.id}>
            <strong>{categoryNames[record.category]}: {verdictNames[record.status]}</strong>
            <RecordDetails record={record} />
          </li>)}</ol> : <p>{basis.storage_status === "empty" || basis.storage_status === "readable" ? "저장된 수동 검수 기록이 없습니다." : "저장된 기록을 표시할 수 없습니다."}</p>}
        </section>
      </details>
    </>}
    {readOnly ? <p>프로젝트를 정상적으로 열어야 새 검수 기록을 입력할 수 있습니다.</p> : basis && <form onSubmit={event => { event.preventDefault(); void save(); }}>
      <fieldset disabled={busy || !canRecord || loading || saving}>
        <legend>새 수동 검수 기록</legend>
        <p>직접 확인한 항목과 페이지를 선택하고 판단 근거를 남겨 주세요. 통과는 모든 페이지를 확인한 경우에만 기록할 수 있습니다.</p>
        <div className="review-form-grid">
          <div className="field"><label>검수 항목<select value={form.category} onChange={event => setForm(value => ({ ...value, category: event.target.value as Form["category"] }))}>
            <option value="">선택하세요</option>
            {(Object.keys(categoryNames) as Category[]).map(category => <option key={category} value={category}>{categoryNames[category]}</option>)}
          </select></label></div>
          <div className="field"><label>판정<select value={form.status} onChange={event => setForm(value => ({ ...value, status: event.target.value as Form["status"] }))}>
            <option value="">선택하세요</option>
            <option value="needs_revision">수정 필요</option><option value="passed">통과</option>
          </select></label></div>
        </div>
        <div className="field"><label>검수자<input maxLength={200} value={form.reviewer} onChange={event => setForm(value => ({ ...value, reviewer: event.target.value }))} /></label></div>
        <div className="field"><label>판단 근거<textarea maxLength={4000} value={form.note} onChange={event => setForm(value => ({ ...value, note: event.target.value }))} /></label></div>
        <fieldset className="review-pages"><legend>직접 확인한 페이지</legend>
          <div>{Array.from({ length: slideCount }, (_, index) => index + 1).map(page => <label key={page}>
            <input type="checkbox" checked={form.pages.includes(page)} onChange={event => setForm(value => ({ ...value,
              pages: event.target.checked ? [...value.pages, page] : value.pages.filter(selected => selected !== page),
            }))} />{page}페이지 확인
          </label>)}</div>
          <p className="hint">선택한 페이지: {form.pages.length ? [...form.pages].sort((a, b) => a - b).join(", ") : "없음"}</p>
          {form.pages.some(page => page > slideCount) && <p>현재 출력 범위를 벗어난 선택이 있습니다. 페이지 선택을 지운 뒤 다시 확인해 주세요.</p>}
          <button type="button" disabled={!form.pages.length} onClick={() => setForm(value => ({ ...value, pages: [] }))}>페이지 선택 지우기</button>
        </fieldset>
      </fieldset>
      {form.status === "passed" && !fullReview && <p className="hint">통과를 기록하려면 {slideCount}페이지 전체를 직접 확인해 주세요.</p>}
      <div className="actions"><button type="submit" disabled={!canSave}>검수 기록 저장</button></div>
    </form>}
  </section>;
}
