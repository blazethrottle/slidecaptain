import { useEffect, useRef, useState } from "react";
import { api, ApiError, messageOf, type Deck } from "../api/client";

type Props = {
  projectName: string; deck: Deck; disabled: boolean; onApplied: (deck: Deck) => void;
  onBusyChange?: (busy: boolean) => void; onActiveChange: (active: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void; onScreenReady?: (guard: () => Promise<boolean>) => void;
  onConflict?: () => void;
};
type Basis = { base_etag: string; sources_fingerprint: string; evidence_fingerprints: Record<string, string> };
type Preview = Awaited<ReturnType<typeof api.previewDocumentChange>>;
type EvidenceSelection = NonNullable<Deck["structure"]["story_plan"]>["evidence"][number];
const MAX_BYTES = 1024 * 1024;
const jsonText = (value: unknown) => JSON.stringify(value, null, 2);
function selectedText(evidence?: EvidenceSelection) {
  if (!evidence) return "";
  const { source_revision: _revision, excerpt: _excerpt, ...selection } = evidence;
  return jsonText(selection);
}
function parseJson(text: string) {
  if (new TextEncoder().encode(text).byteLength > MAX_BYTES) throw new Error("JSON 입력은 1MiB 이내여야 합니다.");
  try { return JSON.parse(text); } catch { throw new Error("JSON 형식을 확인해 주세요. 입력은 보존되어 있습니다."); }
}

export function DocumentChangePanel(props: Props) {
  return <DocumentChanges key={props.projectName} {...props} />;
}

function DocumentChanges({ projectName, deck, disabled, onApplied, onBusyChange, onActiveChange,
  onDirtyChange, onScreenReady, onConflict }: Props) {
  const evidence = deck.structure.story_plan?.evidence ?? [];
  const [mode, setMode] = useState<"document" | "migration">("document");
  const [candidateText, setCandidateText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [evidenceId, setEvidenceId] = useState(evidence[0]?.id ?? "");
  const [selectionText, setSelectionText] = useState(selectedText(evidence[0]));
  const [migrationEdited, setMigrationEdited] = useState(false);
  const [basis, setBasis] = useState<Basis | null>(null);
  const [result, setResult] = useState<Preview | null>(null);
  const [previewMode, setPreviewMode] = useState<"document" | "migration">("document");
  const [previewInput, setPreviewInput] = useState<unknown>(null);
  const [validPreview, setValidPreview] = useState(false);
  const [checks, setChecks] = useState<string[]>([]);
  const [mustReload, setMustReload] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const owner = useRef(0);
  const pending = useRef(false);
  const mounted = useRef(true);
  const current = useRef({ deck, disabled, file, dirty: false });
  const callbacks = useRef({ onApplied, onBusyChange, onActiveChange, onDirtyChange, onScreenReady, onConflict });
  callbacks.current = { onApplied, onBusyChange, onActiveChange, onDirtyChange, onScreenReady, onConflict };
  const dirty = !!candidateText || file !== null || migrationEdited || result !== null;
  current.current = { deck, disabled, file, dirty };
  const invalidate = () => { ++owner.current; setValidPreview(false); setChecks([]); setError(""); setNotice(""); };
  const clearFile = () => { setFile(null); if (fileInput.current) fileInput.current.value = ""; };
  const reset = () => {
    ++owner.current; setCandidateText(""); clearFile(); setSelectionText(selectedText(evidence[0]));
    setEvidenceId(evidence[0]?.id ?? ""); setMigrationEdited(false); setResult(null); setPreviewInput(null);
    setValidPreview(false); setChecks([]); setError(""); setNotice("");
  };
  const fail = (error: unknown) => {
    setError(error instanceof Error && !(error instanceof ApiError) ? error.message : messageOf(error));
    if (error instanceof ApiError && (error.status === 409 || error.status === 412)) {
      setMustReload(true); setValidPreview(false); setChecks([]);
      if (error.status === 412) callbacks.current.onConflict?.();
    }
  };
  const lease = () => {
    pending.current = true; setWorking(true);
    const notify = callbacks.current.onBusyChange;
    notify?.(true);
    return () => {
      pending.current = false;
      notify?.(false);
      if (mounted.current) setWorking(false);
    };
  };
  const loadBasis = async () => {
    if (pending.current || current.current.disabled) return;
    const id = ++owner.current;
    const release = lease();
    setMustReload(true); setValidPreview(false); setChecks([]); setError("");
    try {
      const response = await api.getDocumentChangeBasis(projectName);
      if (mounted.current && id === owner.current) { setBasis(response); setMustReload(false); }
    } catch (error) { if (mounted.current && id === owner.current) fail(error); }
    finally { release(); }
  };
  useEffect(() => {
    mounted.current = true;
    void loadBasis();
    return () => { mounted.current = false; ++owner.current; };
    // A project owns its requests and selected file; release occurs only at actual settlement.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const priorDeck = useRef(deck);
  useEffect(() => {
    if (priorDeck.current !== deck) {
      priorDeck.current = deck; ++owner.current;
      setMustReload(true); setValidPreview(false); setChecks([]);
      setNotice("저장본이 바뀌었습니다. 입력과 후보를 보존했습니다. 변경 기준을 다시 확인한 뒤 새 미리보기를 만드세요.");
    }
  }, [deck]);
  useEffect(() => { onActiveChange(working || dirty); onDirtyChange?.(dirty); }, [working, dirty, onActiveChange, onDirtyChange]);
  useEffect(() => {
    onScreenReady?.(async () => {
      if (pending.current) return false;
      if (current.current.dirty && !window.confirm("적용하지 않은 문서 변경 입력과 후보를 버리고 이동할까요?")) return false;
      return true;
    });
  });

  const ready = !disabled && !working && !mustReload && !!basis;
  const allConfirmed = !!result && result.losses.length > 0 && checks.length === result.losses.length &&
    result.losses.every(loss => checks.includes(loss.id));
  const preview = async () => {
    if (pending.current || !ready || !basis) return;
    const id = ++owner.current;
    const requestDeck = current.current.deck;
    const requestFile = file;
    const requestMode = mode;
    const release = lease();
    setError(""); setNotice(""); setValidPreview(false); setChecks([]);
    try {
      let input: unknown;
      if (requestMode === "document") {
        if (requestFile && requestFile.size > MAX_BYTES) throw new Error("문서 JSON 파일은 1MiB 이내여야 합니다.");
        input = parseJson(requestFile ? await requestFile.text() : candidateText);
      } else input = parseJson(selectionText);
      if (!mounted.current || id !== owner.current || current.current.deck !== requestDeck ||
        current.current.disabled || current.current.file !== requestFile) return;
      const response = requestMode === "document"
        ? await api.previewDocumentChange(projectName, { candidate: input as Deck, expected_source_fingerprint: basis.sources_fingerprint }, basis.base_etag)
        : await api.previewEvidenceMigration(projectName, {
          evidence_id: evidenceId, old_evidence_fingerprint: basis.evidence_fingerprints[evidenceId],
          new_selection: input as Omit<EvidenceSelection, "source_revision" | "excerpt">,
          expected_source_fingerprint: basis.sources_fingerprint,
        }, basis.base_etag);
      if (mounted.current && id === owner.current && current.current.deck === requestDeck) {
        setResult(response); setPreviewMode(requestMode); setPreviewInput(input); setValidPreview(true);
        setNotice("후보의 변경 내용을 표시했습니다. 아직 저장하지 않았습니다.");
      }
    } catch (error) { if (mounted.current && id === owner.current) fail(error); }
    finally { release(); }
  };
  const apply = async () => {
    if (pending.current || !ready || !validPreview || !result || !basis || !allConfirmed) return;
    const id = ++owner.current;
    const requestDeck = current.current.deck;
    const release = lease(); setError(""); setNotice("");
    try {
      const confirmation = { expected_source_fingerprint: basis.sources_fingerprint,
        confirmation_token: result.confirmation_token, acknowledged_loss_ids: checks };
      const saved = previewMode === "document"
        ? await api.applyDocumentChange(projectName, { ...confirmation, candidate: result.candidate }, basis.base_etag)
        : await api.applyEvidenceMigration(projectName, { ...confirmation, evidence_id: evidenceId,
          old_evidence_fingerprint: basis.evidence_fingerprints[evidenceId],
          new_selection: previewInput as Omit<EvidenceSelection, "source_revision" | "excerpt"> }, basis.base_etag);
      if (mounted.current && id === owner.current && current.current.deck === requestDeck) {
        reset(); setMustReload(true); setNotice("변경을 적용했습니다. 내용과 현재 PPTX 표시의 독립 검수가 필요합니다.");
        priorDeck.current = saved;
        callbacks.current.onApplied(saved);
      }
    } catch (error) { if (mounted.current && id === owner.current) {
      fail(error);
      if(error instanceof ApiError && error.status===422){setValidPreview(false);setChecks([]);}
    } }
    finally { release(); }
  };

  return <section aria-label="문서 전체 변경과 근거 이동" className="story-rewrite">
    <h2>문서 전체 변경과 근거 이동</h2>
    <p>입력한 후보의 변경 전후를 확인한 뒤 저장합니다. 근거의 의미와 내용, 실제 PowerPoint 표시는 별도 독립 검수가 필요합니다.</p>
    <button disabled={disabled || working} onClick={() => void loadBasis()}>변경 기준 다시 확인</button>
    {working && <p role="status">변경 기준 또는 후보를 확인 중입니다...</p>}
    {mustReload && <p className="notice">변경 기준을 다시 확인하고 새 미리보기를 만들어야 합니다. 입력과 이전 후보는 유지됩니다.</p>}
    <label>변경 방식<select aria-label="변경 방식" value={mode} disabled={disabled || working}
      onChange={e => { invalidate(); setMode(e.target.value as typeof mode); }}>
      <option value="document">문서 전체 후보</option><option value="migration">기존 근거 이동</option>
    </select></label>
    {mode === "document" ? <>
      <label>문서 후보 JSON<textarea aria-label="문서 후보 JSON" rows={8} value={candidateText} disabled={disabled || working}
        onChange={e => { invalidate(); setCandidateText(e.target.value); clearFile(); }} /></label>
      <label>문서 후보 JSON 파일<input ref={fileInput} type="file" aria-label="문서 후보 JSON 파일" accept=".json,application/json" disabled={disabled || working}
        onChange={e => { invalidate(); setFile(e.target.files?.[0] ?? null); }} /></label>
      {file && <p>선택한 파일: {file.name}</p>}
      <p>파일과 텍스트는 1MiB 이내입니다. 보호 도식·차트의 종류, 근거 참조와 장부는 유지해야 합니다.</p>
    </> : <>
      <label>이동할 기존 근거<select aria-label="이동할 기존 근거" value={evidenceId} disabled={disabled || working}
        onChange={e => { invalidate(); setEvidenceId(e.target.value); setSelectionText(selectedText(evidence.find(item => item.id === e.target.value))); setMigrationEdited(false); }}>
        {evidence.map(item => <option key={item.id} value={item.id}>{item.id}: {item.source_id}</option>)}
      </select></label>
      <label>새 근거 선택 JSON<textarea aria-label="새 근거 선택 JSON" rows={8} value={selectionText} disabled={disabled || working}
        onChange={e => { invalidate(); setSelectionText(e.target.value); setMigrationEdited(true); }} /></label>
      <p>기존 ID를 유지하고 자료명과 행 위치를 선택하세요. 새 발췌와 자료 해시는 서버가 확인합니다. 같은 자료의 여러 근거가 낡았다면 한 건씩 자동 이동할 수 없습니다. 여러 건을 함께 이동하는 기능은 아직 지원하지 않습니다.</p>
    </>}
    <button disabled={!ready || (mode === "document" ? !file && !candidateText.trim() : !evidenceId || !selectionText.trim() || !basis?.evidence_fingerprints[evidenceId])}
      onClick={() => void preview()}>변경 미리보기</button>
    {dirty && <button disabled={working} onClick={() => { if (window.confirm("입력과 변경 후보를 버릴까요?")) reset(); }}>변경 입력 취소</button>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {result && <section aria-label="아직 적용하지 않은 문서 변경 후보">
      <h3>변경 전후 확인</h3><p>{result.notice}</p>
      {!validPreview && <p className="notice">현재 입력의 적용 후보가 아닙니다. 입력을 보존하고 새 미리보기를 만드세요.</p>}
      {result.losses.map((loss, index) => <article key={loss.id}>
        <h4>{index + 1}. {loss.path} ({loss.kind})</h4>
        <p>변경 전</p><pre aria-label={`${index + 1}번 변경 전`}>{jsonText(loss.before)}</pre>
        <p>변경 후</p><pre aria-label={`${index + 1}번 변경 후`}>{jsonText(loss.after)}</pre>
        <label><input type="checkbox" aria-label={`${index + 1}번 변경 내용 확인`} checked={checks.includes(loss.id)} disabled={!ready || !validPreview}
          onChange={e => setChecks(items => e.target.checked ? [...new Set([...items, loss.id])] : items.filter(id => id !== loss.id))} />이 변경 내용을 확인했습니다</label>
      </article>)}
      <button disabled={!ready || !validPreview || !allConfirmed} onClick={() => void apply()}>확인한 변경 적용</button>
      <p>변경 적용은 제출 승인이 아닙니다. 적용 후 현재 PPTX의 내용과 실제 표시를 독립적으로 검수해야 합니다.</p>
    </section>}
  </section>;
}
