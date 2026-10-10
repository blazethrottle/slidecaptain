import { useEffect, useRef, useState } from "react";
import { api, ApiError, messageOf, type ProjectInfo, type UploadResult } from "../api/client";
import type { SaveStatus } from "../ui/StatusIndicator";
import { Button } from "../ui/Button";

const KEPT_SOURCE_NOTICE = "수정 중인 자료 내용을 보존했습니다. 저장한 뒤 다른 자료를 다시 열어 주세요.";

// 로드 후 상한을 넘어 잘린 자리를 설명하는 note는 이 접두사로 시작한다(backend/slidecaptain/sources/xlsx.py
// _build_extraction). 이 note만 잘림 알림으로 따로 빼고, 나머지(계산값 없음 건수 등)는 결과 안내
// 뒤에 붙인다(계획서 B4)
const LIMIT_NOTE_PREFIX = "(한계:";

function limitReasons(notes: string[]): string[] {
  return notes.filter((n) => n.startsWith(LIMIT_NOTE_PREFIX)).map((n) => n.slice(LIMIT_NOTE_PREFIX.length, -1).trim());
}

function otherNotes(notes: string[]): string[] {
  return notes.filter((n) => !n.startsWith(LIMIT_NOTE_PREFIX));
}

// 자료 단계 (개정판 D3a-2). 보고 정보는 보고 목적 단계(ReportPurposeScreen)로 옮겼다. 이 화면은 덱을 쓰지 않는다
export function SourcesScreen({
  project, onDirtyChange, onScreenReady, onBusyChange, onSaveStatusChange,
}: {
  project: ProjectInfo;
  // 자료 본문이 저장본과 다르거나 업로드가 진행 중이면 참 (beforeunload 경고용)
  onDirtyChange?: (dirty: boolean) => void;
  onScreenReady?: (flush: (() => Promise<boolean>) | null) => void;  // 부모(ProjectView)가 단계를 옮기기 전에 확인하도록
  onBusyChange?: (busy: boolean) => void;  // 업로드 진행 중이면 부모가 단계 이동 등 이동 경로를 잠근다(계획서 B4)
  onSaveStatusChange?: (status: SaveStatus) => void;  // 상단 머리의 저장 상태 (계획 4.1 저장 상태 출처 표)
}) {
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState("");
  const textRef = useRef(text);
  textRef.current = text;
  const savedText = useRef("");
  const sourceDirty = selected !== null && text !== savedText.current;
  const sourceRequest = useRef(0);
  const [sourceSaving, setSourceSaving] = useState(false);
  const sourceSavePending = useRef(false);
  const [newName, setNewName] = useState("");
  const [notice, setNotice] = useState("");
  // 저장 성공 안내는 오류 알림(role=alert)과 나눈다: 성공이 빨간 경고로 보이지 않게 (D2a-4)
  const [success, setSuccess] = useState("");
  useEffect(() => { if (notice) setSuccess(""); }, [notice]);
  const [info, setInfo] = useState("");  // 성공 안내 (오류 영역과 분리, 파일럿 관찰 1)
  const [truncationNotice, setTruncationNotice] = useState("");  // 잘린 파일 알림 (오류 아님, 결과 안내와 별도)
  const [uploading, setUploading] = useState(false);  // 업로드 진행 중 (계획서 B4 가정 7)
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; ++sourceRequest.current; };
  }, []);

  // 두 신호가 서로 덮지 않도록 한 효과에서 계산해 올린다: 자료 본문 미저장 또는 업로드 진행 중이면 참
  // (계획서 B4 가정 7)
  useEffect(() => {
    onDirtyChange?.(uploading || sourceDirty);
  }, [uploading, sourceDirty, onDirtyChange]);
  const [lastSaveFailed, setLastSaveFailed] = useState(false);
  useEffect(() => {
    onSaveStatusChange?.({ kind: sourceSaving ? "saving" : lastSaveFailed ? "save_failed" : sourceDirty ? "unsaved" : "saved" });
  }, [sourceSaving, lastSaveFailed, sourceDirty, onSaveStatusChange]);

  // 저장한 뒤 내용을 다시 고치거나 다른 자료를 열면 지난 성공 안내를 지운다 (D2a-4 리뷰 R1)
  useEffect(() => { setSuccess(""); }, [text, selected]);

  useEffect(() => {
    onScreenReady?.(async () => {
      if (textRef.current !== savedText.current) {
        setNotice("이동하기 전에 자료 저장 버튼으로 수정한 내용을 저장해 주세요.");
        return false;
      }
      return true;
    });
    return () => onScreenReady?.(null);  // 다음 화면이 이 화면의 낡은 플러시를 들고 있지 않게 한다
  }, [onScreenReady]);

  const reload = () => {
    api.listSources(project.name).then(setFiles).catch((e) => setNotice(messageOf(e)));
  };
  useEffect(reload, [project.name]);

  const open = async (f: string) => {
    if (textRef.current !== savedText.current) {
      setNotice("다른 자료를 열기 전에 자료 저장 버튼으로 수정한 내용을 저장해 주세요.");
      return;
    }
    const request = ++sourceRequest.current;
    try {
      const s = await api.readSource(project.name, f);
      if (request !== sourceRequest.current || !mountedRef.current) return;
      if (textRef.current !== savedText.current) {
        setNotice(KEPT_SOURCE_NOTICE);
        return;
      }
      setSelected(f);
      setText(s.text);
      savedText.current = s.text;
      setNotice("");
    } catch (e) {
      if (request === sourceRequest.current && mountedRef.current) setNotice(messageOf(e));
    }
  };

  const saveText = async () => {
    if (selected === null || sourceSavePending.current) return;
    const request = sourceRequest.current;
    sourceSavePending.current = true;
    setSourceSaving(true);
    try {
      await api.writeSource(project.name, selected, text);
      if (request !== sourceRequest.current || !mountedRef.current) return;
      savedText.current = text;
      setLastSaveFailed(false);
      onDirtyChange?.(textRef.current !== text);
      setNotice("");
      setSuccess("자료를 저장했습니다.");
    } catch (e) {
      if (request === sourceRequest.current && mountedRef.current) { setNotice(messageOf(e)); setLastSaveFailed(true); }
    } finally {
      sourceSavePending.current = false;
      if (mountedRef.current) setSourceSaving(false);
    }
  };

  const addFile = async () => {
    if (textRef.current !== savedText.current) {
      setNotice("자료를 추가하기 전에 수정한 자료 내용을 저장해 주세요.");
      return;
    }
    const base = newName.trim();
    const f = base.includes(".") ? base : `${base}.md`;
    try {
      await api.writeSource(project.name, f, "");
      setNewName("");
      reload();
      await open(f);
    } catch (e) {
      setNotice(messageOf(e));
    }
  };

  const importFiles = async (list: FileList | File[]) => {
    if (textRef.current !== savedText.current) {
      setNotice("파일을 가져오기 전에 수정한 자료 내용을 저장해 주세요.");
      return;
    }
    const items = Array.from(list);
    if (items.length === 0) return;
    // 업로드가 이미 진행 중이면 겹쳐 시작하지 않는다: 먼저 응답한 쪽의 finally가 onBusyChange(false)를
    // 불러, 아직 진행 중인 첫 업로드의 잠금(FC-17 업로드 중 단계 이동 방지)을 풀어 버리는 경합을 막는다
    // (B4 리뷰 F1). 파일 입력은 uploading 동안 disabled로도 막지만, 이 확인이 실제 방지선이다
    if (uploading) return;
    setInfo("");  // 지난 안내가 남아 있지 않게 한다
    setSuccess("");
    setTruncationNotice("");
    setUploading(true);
    onBusyChange?.(true);  // 부모(ProjectView)가 단계 이동 등 이동 경로를 잠근다(계획서 B4)
    try {
      let added = 0;
      let skipped = 0;
      let last: string | null = null;
      const failures: string[] = [];
      const results: UploadResult[] = [];  // 파일마다 시트와 셀 수와 잘림 정보를 모은다(계획서 B4)
      for (const f of items) {
        try {
          let result: UploadResult;
          try {
            result = await api.uploadSource(project.name, f, false);
          } catch (e) {
            if (!(e instanceof ApiError) || e.status !== 409) throw e;
            if (!window.confirm(`같은 이름의 자료가 이미 있습니다: ${f.name}. 덮어쓸까요?`)) {
              skipped += 1;
              continue;
            }
            result = await api.uploadSource(project.name, f, true);
          }
          added += 1;
          last = f.name;
          results.push(result);
        } catch (e) {
          failures.push(`${f.name}: ${messageOf(e)}`);
        }
      }
      // 언마운트 뒤에는 이후의 setState를 건너뛴다: 잠금이 있어도 방어적으로(계획서 B4)
      if (!mountedRef.current) return;
      reload();
      if (last !== null) await open(last);  // open이 notice를 비우므로 안내 문구는 그 뒤에 쓴다
      if (!mountedRef.current) return;
      const xlsxResults = results.filter(
        (r): r is UploadResult & { sheets: number; cells: number } => r.sheets !== null,
      );
      const xlsxDetails = xlsxResults.map(
        (r) => `${r.filename}: 시트 ${r.sheets.toLocaleString()}개, 셀 ${r.cells.toLocaleString()}개`,
      );
      // 여러 파일이 각각 note를 남기면 파일명 없이 이어붙어 어느 파일 것인지 구분되지 않았다(B4 리뷰
      // F2). note를 남긴 파일이 둘 이상일 때만 파일명을 접두해 구분한다(한 파일뿐이면 출처가 하나라
      // 모호하지 않으므로 접두하지 않는다)
      const notesByFile = results
        .map((r) => ({ filename: r.filename, notes: otherNotes(r.notes) }))
        .filter((r) => r.notes.length > 0);
      const extraNotes = notesByFile.length > 1
        ? notesByFile.map((r) => `${r.filename}: ${r.notes.join("; ")}`)
        : notesByFile.flatMap((r) => r.notes);
      const summary = added > 0 ? `${added}개 자료를 추가했습니다.` : "추가한 자료가 없습니다.";
      let infoText = summary + (skipped > 0 ? ` 건너뜀 ${skipped}개.` : "");
      if (xlsxDetails.length > 0) infoText += " " + xlsxDetails.join(" / ");
      // 두 블록을 공백 하나로 붙이면 "셀 1,204개 계산값 없음: 2곳"처럼 서로 다른 두 사실이 한
      // 구절로 오독된다. xlsxDetails 블록 뒤에 붙을 때만 마침표로 끊는다(B 묶음 최종 리뷰 minor F-3)
      if (extraNotes.length > 0) infoText += (xlsxDetails.length > 0 ? ". " : " ") + extraNotes.join(" / ");
      setInfo(infoText);
      const truncatedResults = results.filter((r) => r.truncated);
      if (truncatedResults.length > 0) {
        setTruncationNotice(`일부가 잘렸습니다: ${truncatedResults
          .map((r) => `${r.filename} (${limitReasons(r.notes).join("; ")})`).join(" / ")}`);
      }
      if (failures.length > 0) setNotice(`올리지 못한 파일: ${failures.join(" / ")}`);
    } finally {
      if (mountedRef.current) setUploading(false);
      onBusyChange?.(false);  // 잠금은 언마운트 여부와 무관하게 반드시 풀어야 부모가 영구히 잠기지 않는다
    }
  };


  return (
    <div className="sources-screen">
      {/* 편집 중 보존은 오류가 아니라 놓치면 안 되는 주의 안내다 (D2a 이월 6, D3a-1) */}
      {notice && (notice === KEPT_SOURCE_NOTICE
        ? <p role="status" className="notice-warning">{notice}</p>
        : <p role="alert">{notice}</p>)}
      {success && !notice && <p role="status">{success}</p>}
      {info && <p className="info">{info}</p>}
      {truncationNotice && <p className="info truncation">{truncationNotice}</p>}
      <section>
        <h2>입력 자료</h2>
        <p>완성된 리서치 자료(마크다운, 텍스트, CSV, 엑셀)를 넣어 주세요. 탐색기로 프로젝트 폴더의 sources에 파일을 넣어도 됩니다.</p>
        <ul>
          {files.map((f) => (
            <li key={f}><button onClick={() => open(f)}>{f}</button></li>
          ))}
        </ul>
        <div className="drop-zone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); void importFiles(e.dataTransfer.files); }}>
          <p>
            파일을 여기에 끌어다 놓거나 아래에서 선택하세요. 마크다운, 텍스트, CSV, 엑셀(xlsx)을 받을 수 있고,
            생성 시 자료 합계 10만 자 한도가 적용됩니다. 원본 엑셀은 프로젝트 폴더의 uploads 에 보관되고 AI
            에는 추출본만 갑니다. 같은 이름의 기존 자료가 있으면 엑셀 추출본으로 교체됩니다.
          </p>
          {/* 파일 올리기가 자료 단계의 주 행동이다 (D3a-1, 계획 4.6). 라벨이 버튼 모양을 맡는다 */}
          <label className="btn-primary"><span aria-hidden="true">파일 선택</span>
            <input aria-label="자료 파일 선택" type="file" multiple accept=".md,.txt,.csv,.xlsx"
              className="visually-hidden" disabled={uploading}
              onChange={(e) => {
                const picked = e.target.files;
                if (picked) void importFiles(picked);
                e.target.value = "";  // 같은 파일을 다시 골라도 change가 나게 한다
              }} />
          </label>
        </div>
        <div className="field">
          <label>새 자료 이름 <span className="hint">(붙여넣기용 빈 자료를 만듭니다)</span>
            <input aria-label="새 자료 이름" placeholder="예: 리서치.md"
              value={newName} onChange={(e) => setNewName(e.target.value)} />
          </label>
          <div className="actions">
            <button onClick={addFile} disabled={!newName.trim()}>자료 추가</button>
          </div>
        </div>
        {selected !== null && (
          <div>
            <h3>{selected}</h3>
            <div className="field">
              <textarea aria-label="자료 내용" rows={16} value={text} disabled={uploading || sourceSaving}
                onChange={(e) => setText(e.target.value)} />
            </div>
            <div className="actions">
              <button onClick={saveText} disabled={sourceSaving}>자료 저장</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
