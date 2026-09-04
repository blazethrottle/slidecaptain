import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, messageOf, type Deck, type ProjectInfo, type UploadResult } from "../api/client";

const REPORT_TYPES = [
  ["research", "연구분석"],
  ["approval", "승인요청"],
  ["strategy", "전략기획"],
] as const;

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

// 보고 정보 4필드만 비교한다: preset_overrides는 이 화면이 건드리지 않는 필드라 비교에 넣으면
// 다른 탭이 남긴 변경과 무관하게 흔들릴 수 있다
function metaEqual(a: Deck["meta"], b: Deck["meta"]): boolean {
  return a.title === b.title && a.report_type === b.report_type
    && a.presenter === b.presenter && a.audience === b.audience;
}

export function SourcesScreen({
  project, deck, onDeckChange, onDirtyChange, onScreenReady, onConflict, onBusyChange,
}: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  // 보고 정보가 저장본과 다르거나 업로드가 진행 중이면 참 (부모의 beforeunload 경고용, 계획서 B4 가정 7)
  onDirtyChange?: (dirty: boolean) => void;
  onScreenReady?: (flush: (() => Promise<boolean>) | null) => void;  // 부모(ProjectView)가 탭 전환 전에 플러시하도록
  onConflict?: () => void;  // 저장이 412를 받으면 부모가 배너를 띄운다
  onBusyChange?: (busy: boolean) => void;  // 업로드 진행 중이면 부모가 탭 전환 등 이동 경로를 잠근다(계획서 B4)
}) {
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [newName, setNewName] = useState("");
  const [meta, setMeta] = useState(deck.meta);
  const metaRef = useRef(meta);
  metaRef.current = meta;
  const savedMeta = useRef(deck.meta);       // 마지막으로 서버에 실제 반영된 보고 정보
  const [saving, setSaving] = useState(false);
  const saveChain = useRef<Promise<boolean>>(Promise.resolve(true));  // 버튼 저장과 플러시를 한 줄로 직렬화
  const [notice, setNotice] = useState("");
  const [info, setInfo] = useState("");  // 성공 안내 (오류 영역과 분리, 파일럿 관찰 1)
  const [truncationNotice, setTruncationNotice] = useState("");  // 잘린 파일 알림 (오류 아님, 결과 안내와 별도)
  const [uploading, setUploading] = useState(false);  // 업로드 진행 중 (계획서 B4 가정 7)
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);  // 언마운트 뒤 setState를 건너뛰기 위한 방어용 ref

  // 두 신호가 서로 덮지 않도록 한 효과에서 계산해 올린다: 보고 정보 미저장 또는 업로드 진행 중이면 참
  // (계획서 B4 가정 7)
  useEffect(() => {
    onDirtyChange?.(!metaEqual(meta, savedMeta.current) || uploading);
  }, [meta, uploading, onDirtyChange]);

  const doSaveMeta = useCallback(async (target: Deck["meta"]): Promise<boolean> => {
    setSaving(true);
    try {
      const updated = { ...deck, meta: target };
      await api.putDeck(project.name, updated, false);
      savedMeta.current = target;
      onDeckChange(updated);
      setNotice("보고 정보를 저장했습니다.");
      onDirtyChange?.(!metaEqual(metaRef.current, savedMeta.current));
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 412) {
        onConflict?.();
      } else {
        setNotice(messageOf(e));
      }
      return false;
    } finally {
      setSaving(false);
    }
  }, [project.name, deck, onDeckChange, onDirtyChange, onConflict]);

  // 진행 중 저장 뒤에 이어 붙는다: 버튼 클릭 직후 탭을 바꿔도 같은 내용을 낡은 ETag로 다시 보내지 않는다
  const flushMeta = useCallback((): Promise<boolean> => {
    const next = saveChain.current.then(() => {
      if (metaEqual(metaRef.current, savedMeta.current)) return true;  // 저장할 것이 없다
      return doSaveMeta(metaRef.current);
    });
    saveChain.current = next.catch(() => false);
    return next;
  }, [doSaveMeta]);

  useEffect(() => {
    onScreenReady?.(flushMeta);
    return () => onScreenReady?.(null);  // 다음 화면이 이 화면의 낡은 플러시를 들고 있지 않게 한다
  }, [onScreenReady, flushMeta]);

  const reload = () => {
    api.listSources(project.name).then(setFiles).catch((e) => setNotice(messageOf(e)));
  };
  useEffect(reload, [project.name]);

  const open = async (f: string) => {
    try {
      const s = await api.readSource(project.name, f);
      setSelected(f);
      setText(s.text);
      setNotice("");
    } catch (e) {
      setNotice(messageOf(e));
    }
  };

  const saveText = async () => {
    if (selected === null) return;
    try {
      await api.writeSource(project.name, selected, text);
      setNotice("자료를 저장했습니다.");
    } catch (e) {
      setNotice(messageOf(e));
    }
  };

  const addFile = async () => {
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
    const items = Array.from(list);
    if (items.length === 0) return;
    setInfo("");  // 지난 안내가 남아 있지 않게 한다
    setTruncationNotice("");
    setUploading(true);
    onBusyChange?.(true);  // 부모(ProjectView)가 탭 전환 등 이동 경로를 잠근다(계획서 B4)
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
      const extraNotes = results.flatMap((r) => otherNotes(r.notes));
      const summary = added > 0 ? `${added}개 자료를 추가했습니다.` : "추가한 자료가 없습니다.";
      let infoText = summary + (skipped > 0 ? ` 건너뜀 ${skipped}개.` : "");
      if (xlsxDetails.length > 0) infoText += " " + xlsxDetails.join(" / ");
      if (extraNotes.length > 0) infoText += " " + extraNotes.join(" / ");
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

  const saveMeta = () => { void flushMeta(); };

  return (
    <div className="sources-screen">
      {notice && <p role="alert">{notice}</p>}
      {info && <p className="info">{info}</p>}
      {truncationNotice && <p className="info truncation">{truncationNotice}</p>}
      <section>
        <h2>보고 정보</h2>
        <div className="field">
          <label>보고서 제목
            <input aria-label="보고서 제목" value={meta.title} disabled={saving}
              onChange={(e) => setMeta({ ...meta, title: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <label>보고 유형
            <select aria-label="보고 유형" value={meta.report_type} disabled={saving}
              onChange={(e) => setMeta({ ...meta, report_type: e.target.value as Deck["meta"]["report_type"] })}>
              {REPORT_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>보고자 <span className="hint">(이름 또는 부서. 표지에 표기됩니다)</span>
            <input aria-label="보고자" value={meta.presenter ?? ""} disabled={saving}
              onChange={(e) => setMeta({ ...meta, presenter: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <label>피보고자 <span className="hint">(문서에 적히지 않고, 문체와 상세 수준을 맞추는 데만 씁니다)</span>
            <input aria-label="피보고자" value={meta.audience ?? ""} disabled={saving}
              onChange={(e) => setMeta({ ...meta, audience: e.target.value })} />
          </label>
        </div>
        <div className="actions">
          <button onClick={saveMeta} disabled={saving}>보고 정보 저장</button>
        </div>
      </section>
      <section>
        <h2>입력 자료</h2>
        <p>완성된 리서치 자료(마크다운, 텍스트)를 넣어 주세요. 탐색기로 프로젝트 폴더의 sources에 파일을 넣어도 됩니다.</p>
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
          <input aria-label="자료 파일 선택" type="file" multiple accept=".md,.txt,.csv,.xlsx"
            onChange={(e) => {
              const picked = e.target.files;
              if (picked) void importFiles(picked);
              e.target.value = "";  // 같은 파일을 다시 골라도 change가 나게 한다
            }} />
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
              <textarea aria-label="자료 내용" rows={16} value={text}
                onChange={(e) => setText(e.target.value)} />
            </div>
            <div className="actions">
              <button onClick={saveText}>자료 저장</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
