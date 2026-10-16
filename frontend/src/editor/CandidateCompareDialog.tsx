// 장 후보 비교 화면 (D3c-6, 계획 4.7, 4.8). AI가 만든 새 내용은 이 화면에서 반영 단위마다 "지금 문구 유지"와 "새 문구 사용"을
// 고른 뒤에 반영한다. 기본 선택은 서버의 미리 보기가 정한다(다시 생성은 직접 고친 문구만 지금 문구, 축약은 모두 새 문구). 그 뒤의
// 미리 보기는 고른 문구 단위와 사용자가 건드린 요소 수정만 보낸다. 건드리지 않은 요소 수정은 서버가 지금 선택으로 기본값을 다시
// 계산한다(목록 길이가 바뀌면 순번 요소 수정을 지운다, 리뷰 G2). 반영은 마지막 미리 보기가 돌려준 실제 선택과 그 기준 저장본을
// 보낸다. 사용자가 본 결과와 다른 것이 저장되지 않게 하기 위해서다(리뷰 G1). 문서 맨 위층(포털)에 그리고 열려 있는 동안 앱
// 화면을 비활성으로 둔다(크게 보기와 같은 방식)
import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { api, ApiError, savedEtag, type CandidateApplyPreview, type Slots } from "../api/client";
import { reasonText } from "../api/jobs";
import { Button } from "../ui/Button";
import { roleName } from "./directEdit";
import { unitName, unitText } from "./mergeUnits";
import { Preview } from "./Preview";

export type CompareSelection = { keep_current: string[]; drop_edits: string[]; unhide: string[] };
type EditChoice = "keep" | "drop" | "unhide";

const BATCH_ACTIVE = "장 생성 묶음이 진행 중이라 지금은 반영할 수 없습니다. 묶음이 끝난 뒤 다시 반영해 주세요.";
export const STALE_BASE = "이 화면이 연 뒤 다른 곳에서 먼저 저장했습니다. 서버 내용을 다시 읽은 뒤 비교해 주세요.";
const FOCUSABLE = 'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]';

const strip = (etag: string | undefined) => etag?.replace(/^W\//, "").replace(/"/g, "");

// Tab이 멈추는 곳. 라디오 묶음은 브라우저에서 한 곳(고른 라디오, 없으면 첫 라디오)이므로 하나로 센다(리뷰 G3)
function tabStops(box: HTMLElement | null): HTMLElement[] {
  const all = Array.from(box?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []).filter((el) => !el.closest("[inert]"));
  const groups = new Set<string>();
  return all.filter((el) => {
    if (!(el instanceof HTMLInputElement) || el.type !== "radio" || !el.name) return true;
    if (groups.has(el.name)) return false;
    groups.add(el.name);
    return true;
  }).map((el) => (el instanceof HTMLInputElement && el.type === "radio" && el.name ? groupStop(all, el.name) : el));
}

function groupStop(all: HTMLElement[], name: string): HTMLElement {
  const radios = all.filter((el): el is HTMLInputElement => el instanceof HTMLInputElement && el.type === "radio" && el.name === name);
  return radios.find((r) => r.checked) ?? radios[0];
}

export function CandidateCompareDialog({ projectName, jobId, chapterId, title, candidateSlots, onApply, onRegenerate,
  regenerateHint, onStaleBase, onUnavailable, onClose, returnFocus, fallbackFocus }: {
  projectName: string;
  jobId: string;
  chapterId?: string;  // 묶음 행이면 그 장. 단독 행은 비운다
  title: string;  // 장 이름 (예: "2장 시장 현황")
  candidateSlots: Slots;  // 새 문구. 미리 보기 응답에는 지금과 합친 결과만 있다
  // 반영과 그 결과 처리는 부르는 화면이 한다(4.7). baseEtag는 미리 보기의 기준 저장본이다. If-Match로 보내야 미리 보기 뒤에
  // 바뀐 저장본에 반영되지 않는다(리뷰 G1)
  onApply: (selection: CompareSelection, baseEtag: string) => Promise<void>;
  onRegenerate?: () => void;  // 막힌 판정의 "현재 입력으로 다시 생성". 이 화면을 닫은 뒤 부른다(동의 창이 앱 화면 안에 뜬다)
  regenerateHint?: string;  // 다시 생성을 이 화면에서 열 수 없을 때 갈 길(리뷰 G9)
  onStaleBase: () => void;  // 이 탭이 모르는 저장본이 서버에 있다. 부르는 화면의 충돌 경로로 보낸다
  // 미리 보기가 409로 이 후보를 비교할 수 없다고 답했다(다른 곳의 처분, 판정할 수 없는 행). 주면 비교 화면 안의 오류 대신
  // 부르는 화면이 목록을 다시 읽고 안내한다(C1 계획 4.2, 리뷰 PR-06). 주지 않으면 지금처럼 오류 문장을 보인다
  onUnavailable?: (error: ApiError) => void;
  onClose: () => void;
  returnFocus?: RefObject<HTMLElement | null>;
  fallbackFocus?: RefObject<HTMLElement | null>;  // 연 버튼이 사라졌을 때(반영 성공) 초점을 받을 곳
}) {
  const [preview, setPreview] = useState<CandidateApplyPreview | null>(null);
  const [keep, setKeep] = useState<string[] | null>(null);  // 고른 문구 단위. 첫 응답 전에는 서버 기본값
  const [choices, setChoices] = useState<Record<string, EditChoice>>({});  // 사용자가 건드린 요소 수정만
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  const busy = useRef(false);
  busy.current = applying;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const onUnavailableRef = useRef(onUnavailable);
  onUnavailableRef.current = onUnavailable;

  const load = async (units: string[] | null, edits: Record<string, EditChoice>) => {
    const mine = ++seq.current;
    setLoading(true);
    setError("");
    try {
      const body = { ...(chapterId ? { chapter_id: chapterId } : {}), ...(units ? { keep_current: units } : {}),
        ...(Object.keys(edits).length > 0 ? { edit_choices: edits } : {}) };
      const next = await api.previewCandidate(projectName, jobId, body);
      if (mine !== seq.current) return;
      // 미리 보기는 서버 저장본으로 계산한다. 이 탭이 모르는 저장본이면 "지금"이 화면과 다르다 (계획 4.7의 1)
      const known = strip(savedEtag(projectName));
      if (known && known !== next.base_etag) { onStaleBase(); return; }
      setPreview(next);
      setKeep(next.keep_current);
    } catch (e) {
      if (mine !== seq.current) return;
      if (e instanceof ApiError && e.status === 409 && onUnavailableRef.current) { onUnavailableRef.current(e); return; }
      setError(e instanceof ApiError ? e.message : "비교 내용을 불러오지 못했습니다. 다시 열어 주세요.");
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load(null, {});
    return () => { seq.current++; };  // 닫은 뒤 도착한 응답은 버린다. 닫은 화면에서 충돌 안내를 띄우지 않는다(리뷰 G18)
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const opener = returnFocus?.current ?? (document.activeElement as HTMLElement | null);
    const root = document.getElementById("root");
    root?.setAttribute("inert", "");
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.querySelector<HTMLElement>("h2")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        if (!busy.current) onCloseRef.current();  // 반영 중에는 닫지 않는다. 닫아도 요청은 진행된다
        return;
      }
      if (e.key !== "Tab") return;
      const stops = tabStops(dialogRef.current);
      if (stops.length === 0) return;
      const active = document.activeElement as HTMLElement | null;
      // 고르지 않은 라디오에 초점이 있어도 그 묶음의 정지점으로 본다
      const at = active instanceof HTMLInputElement && active.type === "radio" && active.name
        ? stops.findIndex((el) => el instanceof HTMLInputElement && el.name === active.name)
        : stops.indexOf(active as HTMLElement);
      if (e.shiftKey && (at <= 0)) { e.preventDefault(); stops[stops.length - 1].focus(); }
      else if (!e.shiftKey && (at === -1 || at === stops.length - 1)) { e.preventDefault(); stops[0].focus(); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      root?.removeAttribute("inert");
      document.body.style.overflow = overflow;
      if (opener?.isConnected) opener.focus();
      else fallbackFocus?.current?.focus();
    };
  }, [returnFocus, fallbackFocus]);

  const toggleUnit = (unit: string, keepIt: boolean) => {
    if (!keep) return;
    const rest = keep.filter((u) => u !== unit);
    const next = keepIt ? [...rest, unit] : rest;
    setKeep(next);
    void load(next, choices);
  };
  const setEdit = (key: string, how: EditChoice) => {
    if (!keep) return;
    const next = { ...choices, [key]: how };
    setChoices(next);
    void load(keep, next);
  };

  const apply = async () => {
    if (!preview || applying) return;
    setApplying(true);
    try {
      // 마지막 미리 보기의 실제 선택이다. 반영은 로딩과 오류가 없을 때만 열리므로 화면의 선택과 같다
      await onApply({ keep_current: preview.keep_current, drop_edits: preview.drop_edits, unhide: preview.unhide },
        preview.base_etag);
    } finally {
      setApplying(false);
    }
  };

  const template = candidateSlots.template;
  const blocked = preview?.blocked_reasons ?? [];
  const batchActive = blocked.includes("batch_active");
  const reasons = blocked.filter((r) => r !== "batch_active");
  const edited = preview?.edited_units ?? null;
  const replacing = edited && keep ? edited.filter((u) => !keep.includes(u)).length : 0;
  const currentEdits = preview?.current?.direct_edits ?? {};
  // 다시 계산한 미리 보기가 실패하면 화면의 선택과 미리 보기가 다르므로 반영하지 않는다(리뷰 G5)
  const canApply = !!preview && !error && !loading && !applying && blocked.length === 0 && preview.merged !== null;
  const editHow = (key: string): EditChoice => choices[key]
    ?? (preview?.drop_edits.includes(key) ? "drop" : preview?.unhide.includes(key) ? "unhide" : "keep");

  return createPortal(
    <div className="compare-overlay">
      <div ref={dialogRef} className="compare-dialog" role="dialog" aria-modal="true" aria-labelledby="compare-title"
        aria-busy={loading || applying}>
        <h2 id="compare-title" tabIndex={-1}>{title}: 새 내용과 비교</h2>
        {error && <p role="alert">{error}</p>}
        {!preview && loading && <p>비교 내용을 불러오고 있습니다.</p>}
        {preview && (<>
          {batchActive && <p role="status" className="notice-warning">{BATCH_ACTIVE}</p>}
          {reasons.length > 0 && (
            <div role="status" className="notice-warning">
              <p>이전 입력 기준 후보라 반영할 수 없습니다({reasonText(reasons)}). 비교는 볼 수 있습니다.</p>
              {onRegenerate ? <Button onClick={() => { onClose(); onRegenerate(); }}>현재 입력으로 다시 생성</Button>
                : regenerateHint && <p>{regenerateHint}</p>}
            </div>
          )}
          {preview.notices.includes("deck_changed_elsewhere") && (
            <p className="notice">덱의 다른 부분이 바뀌었지만 이 장의 입력은 그대로입니다.</p>)}
          {preview.current && edited === null && (
            <p className="hint">이 장은 반영 기록이 없어 직접 고친 문구를 표시하지 않습니다. 기본 선택은 모두 새 문구입니다.</p>)}
          {preview.already_applied && <p className="notice">지금 내용과 같아 바뀌는 것이 없습니다. 반영하면 이 결과만 처리됩니다.</p>}
          <div className="compare-previews">
            <figure>
              <figcaption>지금</figcaption>
              {preview.current_plan ? (
                <div inert aria-hidden="true">
                  <Preview slide={preview.current_plan} style={preview.style} pageW={preview.page_width_pt}
                    pageH={preview.page_height_pt} selected={null} onSelect={() => {}} onCommitText={() => {}}
                    template={template} edits={currentEdits} />
                </div>
              ) : <p className="hint">아직 내용이 없습니다.</p>}
            </figure>
            <figure>
              <figcaption>반영 뒤</figcaption>
              {preview.merged_plan ? (
                <div inert aria-hidden="true">
                  <Preview slide={preview.merged_plan} style={preview.style} pageW={preview.page_width_pt}
                    pageH={preview.page_height_pt} selected={null} onSelect={() => {}} onCommitText={() => {}}
                    template={template} edits={preview.merged?.direct_edits ?? {}} />
                </div>
              ) : <p className="hint">이 장에는 합칠 수 없습니다.</p>}
            </figure>
          </div>
          {preview.warnings.length > 0 && (
            <section>
              <h3>반영 뒤 경고</h3>
              <ul>{preview.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
            </section>
          )}
          <section>
            <h3>문구</h3>
            {preview.units.map((unit) => {
              const kept = keep?.includes(unit) ?? false;
              const isEdited = edited?.includes(unit) ?? false;
              return (
                <fieldset key={unit} className="compare-unit" disabled={applying}>
                  <legend>{unitName(template, unit)}{isEdited && <span className="compare-badge"> (직접 고친 문구)</span>}</legend>
                  {preview.length_changed_units.includes(unit) && (
                    <p className="hint">새 내용의 항목 수와 순서가 다릅니다.</p>)}
                  <div className="compare-texts">
                    <div><strong>지금</strong><pre>{unitText(preview.current?.slots, template, unit) || "(없음)"}</pre></div>
                    <div><strong>새 문구</strong><pre>{unitText(candidateSlots, template, unit) || "(없음)"}</pre></div>
                  </div>
                  <label><input type="radio" name={`unit-${unit}`} checked={kept} disabled={!preview.current}
                    onChange={() => toggleUnit(unit, true)} /> 지금 문구 유지</label>
                  <label><input type="radio" name={`unit-${unit}`} checked={!kept}
                    onChange={() => toggleUnit(unit, false)} /> 새 문구 사용</label>
                </fieldset>
              );
            })}
          </section>
          {Object.keys(currentEdits).length > 0 && (
            <section>
              <h3>위치와 서식 수정</h3>
              {Object.entries(currentEdits).map(([key, edit]) => {
                const how = editHow(key);
                const name = roleName(key, template);
                // 합친 결과에 이 요소가 없으면 무엇을 골라도 수정이 사라진다. 고를 수 없게 두고 그 사실을 적는다(리뷰 G13)
                // removed_edits에는 지우기로 고른 열쇠도 든다. 고르지 않았는데 사라지는 열쇠만 자리가 없는 것이다
                const gone = preview.removed_edits.includes(key) && !preview.drop_edits.includes(key);
                return (
                  <fieldset key={key} className="compare-edit" disabled={applying || gone}>
                    <legend>{name}의 위치와 서식{edit.hidden ? " (숨김)" : ""}</legend>
                    {gone && <p className="hint">새 내용에 이 요소가 없어 반영하면 수정이 사라집니다.</p>}
                    <label><input type="radio" name={`edit-${key}`} checked={how === "keep"}
                      onChange={() => setEdit(key, "keep")} /> 유지</label>
                    {edit.hidden && <label><input type="radio" name={`edit-${key}`} checked={how === "unhide"}
                      onChange={() => setEdit(key, "unhide")} /> 숨김만 풀기</label>}
                    <label><input type="radio" name={`edit-${key}`} checked={how === "drop"}
                      onChange={() => setEdit(key, "drop")} /> 지우기</label>
                  </fieldset>
                );
              })}
            </section>
          )}
          {(preview.removed_spans > 0 || preview.removed_chart) && (
            <p className="hint">
              {preview.removed_spans > 0 && `문구가 바뀌는 곳의 부분 강조 ${preview.removed_spans}개가 지워집니다. `}
              {preview.removed_chart && "비교 차트가 지워집니다."}
            </p>
          )}
        </>)}
        <div className="compare-actions">
          {replacing > 0 && <p>직접 고친 문구 {replacing}곳이 새 문구로 바뀝니다.</p>}
          <p className="hint">반영한 뒤 되돌리면 덱은 돌아가지만 이 결과는 다시 반영할 수 없습니다.</p>
          <Button variant="primary" disabled={!canApply} onClick={() => void apply()}>
            {applying ? "반영하는 중" : "반영"}</Button>
          <button disabled={applying} onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
