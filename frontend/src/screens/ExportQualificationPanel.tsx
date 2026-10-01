import { useEffect, useRef, useState } from "react";
import { api, messageOf, type ExportQualification, type IndependentReviewRequest } from "../api/client";
import type { ReviewLeaveGuard } from "./ReviewRecordsPanel";

type Props = { projectName: string; exportId: string; readOnly?: boolean; busy?: boolean;
  onBusyChange?: (busy: boolean) => void; onDirtyChange?: (dirty: boolean) => void; onLeaveReady?: (guard: ReviewLeaveGuard | null) => void };
const renderNames = { not_run: "미수행", rendered: "실행됨", failed: "실행 실패", stale: "현재 출력에 적용 불가", unavailable: "확인 불가" };
const reviewNames = { not_run: "미수행", passed: "서명 검수 통과", needs_revision: "수정 필요", stale: "현재 출력에 적용 불가", unavailable: "확인 불가" };

export function ExportQualificationPanel(props: Props) {
  return <Qualification key={`${props.projectName}/${props.exportId}`} {...props} />;
}

function Qualification({ projectName, exportId, readOnly = false, busy = false, onBusyChange, onDirtyChange, onLeaveReady }: Props) {
  const [basis, setBasis] = useState<ExportQualification | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [mustReload, setMustReload] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const owner = useRef(0);
  const pending = useRef(false);
  const externalBusy = useRef(busy);
  const externalReadOnly = useRef(readOnly);
  const selectedFile = useRef(file);
  externalBusy.current = busy;
  externalReadOnly.current = readOnly;
  selectedFile.current = file;
  const callbacks = useRef({ onBusyChange, onDirtyChange, onLeaveReady });
  callbacks.current = { onBusyChange, onDirtyChange, onLeaveReady };

  const load = async () => {
    if (pending.current) return;
    const id = ++owner.current;
    setLoading(true); setMustReload(true); setError("");
    try {
      const result = await api.getExportQualification(projectName, exportId);
      if (id === owner.current) { setBasis(result); setMustReload(false); }
    } catch (e) { if (id === owner.current) setError(messageOf(e)); }
    finally { if (id === owner.current) setLoading(false); }
  };

  useEffect(() => {
    void load();
    callbacks.current.onLeaveReady?.(async () => {
      if (pending.current) return false;
      return !selectedFile.current || window.confirm("선택한 독립 검수 파일을 적용하지 않고 이동하시겠습니까?");
    });
    return () => { ++owner.current; callbacks.current.onLeaveReady?.(null); callbacks.current.onDirtyChange?.(false); };
    // One keyed project/export owns all late responses.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { callbacks.current.onDirtyChange?.(file !== null); }, [file]);

  const run = async (kind: "render" | "review" | "publish") => {
    if (readOnly || pending.current || externalBusy.current || loading || mustReload || !basis?.base_etag ||
      !basis.input_fingerprint || !basis.artifact_sha256) return;
    const id = ++owner.current;
    const notifyBusy = callbacks.current.onBusyChange;
    pending.current = true; setWorking(true); notifyBusy?.(true);
    setError(""); setNotice("");
    const expected = { expected_input_fingerprint: basis.input_fingerprint, expected_artifact_sha256: basis.artifact_sha256 };
    try {
      if (kind === "render") {
        if (!basis.can_render) return;
        const result = await api.renderExport(projectName, exportId, expected, basis.base_etag);
        if (id === owner.current) { setBasis(result); setNotice("렌더 실행 결과를 기록했습니다."); }
      } else if (kind === "review") {
        if (!file || !basis.can_import_review) return;
        if (file.size > 128 * 1024) throw new Error("검수 파일의 크기 한도를 넘었습니다.");
        let input: IndependentReviewRequest;
        try { input = JSON.parse(await file.text()) as IndependentReviewRequest; }
        catch { throw new Error("서명된 검수 파일을 읽지 못했습니다."); }
        // The file's signed payload remains intact; the server validates trust and coverage.
        if (id !== owner.current || externalBusy.current || externalReadOnly.current) return;
        const result = await api.importIndependentReview(projectName, exportId, { ...input, ...expected }, basis.base_etag);
        if (id === owner.current) { setBasis(result); setFile(null); setNotice("독립 검수 기록의 서명을 확인하고 저장했습니다."); }
      } else {
        if (!basis.final_export_allowed) return;
        const result = await api.publishFinal(projectName, exportId, expected, basis.base_etag);
        if (id === owner.current) { setNotice(`검수한 파일과 같은 내용으로 제출본을 게시했습니다: ${result.pptx_path}`); }
      }
    } catch (e) {
      if (id === owner.current) {
        setError(e instanceof Error && !("status" in e) ? e.message : messageOf(e));
        setMustReload(true); // A selected signed file is preserved across 409/412.
      }
    } finally {
      // Even an unmounted request owns its lease until its actual settlement.
      notifyBusy?.(false);
      if (id === owner.current) { pending.current = false; setWorking(false); }
    }
  };

  const disabled = readOnly || busy || working || loading || mustReload;
  return <section aria-label="제출본 검수와 게시" className="qualification-panel">
    <h4>제출본 검수와 게시</h4>
    <p>실제 PowerPoint 출력과 등록된 독립 검수 기록을 확인합니다. 수동 통과 입력만으로 제출본을 승인하지 않습니다.</p>
    {loading && <p role="status">현재 출력과 검수 기준 확인 중...</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {basis && <>
      <p>목표 PowerPoint 렌더: {renderNames[basis.render_status]}. 독립 검수: {reviewNames[basis.independent_review_status]}.</p>
      <p>{basis.final_export_allowed ? "현재 파일의 제출 조건을 충족했습니다." : "아직 제출본으로 게시할 수 없습니다."}</p>
      {basis.blockers.length > 0 && <ul>{basis.blockers.map((item, i) => <li key={i}>{item}</li>)}</ul>}
      {basis.render?.environment && <details><summary>확인한 렌더 환경</summary>
        {Object.entries(basis.render.environment).map(([key, value]) => <p key={key}>{key}: {value}</p>)}
      </details>}
      {basis.independent_review && <p>검수자: {basis.independent_review.receipt.reviewer_id}. 검수 페이지: {basis.independent_review.receipt.pages.join(", ")}.</p>}
    </>}
    <button disabled={busy || working || loading} onClick={() => void load()}>제출 기준 다시 확인</button>
    {!readOnly && <>
      <button disabled={disabled || !basis?.can_render} onClick={() => void run("render")}>PowerPoint 렌더 실행</button>
      <label>서명된 독립 검수 파일<input aria-label="서명된 독립 검수 파일" type="file" accept=".json,application/json" disabled={disabled}
        onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
      {file && <p>선택한 검수 파일: {file.name}</p>}
      <button disabled={disabled || !file || !basis?.can_import_review} onClick={() => void run("review")}>독립 검수 기록 확인</button>
      <button disabled={disabled || !basis?.final_export_allowed} onClick={() => void run("publish")}>검수한 파일을 제출본으로 게시</button>
    </>}
  </section>;
}
