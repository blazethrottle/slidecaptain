import { useEffect, useState } from "react";
import { api, ApiError, messageOf, type Deck, type ProjectInfo } from "../api/client";

const REPORT_TYPES = [
  ["research", "연구분석"],
  ["approval", "승인요청"],
  ["strategy", "전략기획"],
] as const;

export function SourcesScreen({ project, deck, onDeckChange }: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
}) {
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [newName, setNewName] = useState("");
  const [meta, setMeta] = useState(deck.meta);
  const [notice, setNotice] = useState("");
  const [info, setInfo] = useState("");  // 성공 안내 (오류 영역과 분리, 파일럿 관찰 1)

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
    let added = 0;
    let skipped = 0;
    let last: string | null = null;
    const failures: string[] = [];
    for (const f of items) {
      try {
        try {
          await api.uploadSource(project.name, f, false);
        } catch (e) {
          if (!(e instanceof ApiError) || e.status !== 409) throw e;
          if (!window.confirm(`같은 이름의 자료가 이미 있습니다: ${f.name}. 덮어쓸까요?`)) {
            skipped += 1;
            continue;
          }
          await api.uploadSource(project.name, f, true);
        }
        added += 1;
        last = f.name;
      } catch (e) {
        failures.push(`${f.name}: ${messageOf(e)}`);
      }
    }
    reload();
    if (last !== null) await open(last);  // open이 notice를 비우므로 안내 문구는 그 뒤에 쓴다
    const summary = added > 0 ? `${added}개 자료를 추가했습니다.` : "추가한 자료가 없습니다.";
    setInfo(summary + (skipped > 0 ? ` 건너뜀 ${skipped}개.` : ""));
    if (failures.length > 0) setNotice(`올리지 못한 파일: ${failures.join(" / ")}`);
  };

  const saveMeta = async () => {
    const updated = { ...deck, meta };
    try {
      await api.putDeck(project.name, updated, false);
      onDeckChange(updated);
      setNotice("보고 정보를 저장했습니다.");
    } catch (e) {
      setNotice(messageOf(e));
    }
  };

  return (
    <div className="sources-screen">
      {notice && <p role="alert">{notice}</p>}
      {info && <p className="info">{info}</p>}
      <section>
        <h2>보고 정보</h2>
        <label>보고서 제목
          <input aria-label="보고서 제목" value={meta.title}
            onChange={(e) => setMeta({ ...meta, title: e.target.value })} />
        </label>
        <label>보고 유형
          <select aria-label="보고 유형" value={meta.report_type}
            onChange={(e) => setMeta({ ...meta, report_type: e.target.value as Deck["meta"]["report_type"] })}>
            {REPORT_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
        <label>피보고자
          <input aria-label="피보고자" value={meta.audience ?? ""}
            onChange={(e) => setMeta({ ...meta, audience: e.target.value })} />
        </label>
        <button onClick={saveMeta}>보고 정보 저장</button>
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
          <p>파일을 여기에 끌어다 놓거나 아래에서 선택하세요. 지금은 .md, .txt, .csv만 되고, 생성 시 자료 합계 10만 자 한도가 적용됩니다.</p>
          <input aria-label="자료 파일 선택" type="file" multiple accept=".md,.txt,.csv"
            onChange={(e) => {
              const picked = e.target.files;
              if (picked) void importFiles(picked);
              e.target.value = "";  // 같은 파일을 다시 골라도 change가 나게 한다
            }} />
        </div>
        <input aria-label="새 자료 이름" placeholder="새 자료 이름"
          value={newName} onChange={(e) => setNewName(e.target.value)} />
        <button onClick={addFile} disabled={!newName.trim()}>자료 추가</button>
        {selected !== null && (
          <div>
            <h3>{selected}</h3>
            <textarea aria-label="자료 내용" rows={16} value={text}
              onChange={(e) => setText(e.target.value)} />
            <button onClick={saveText}>자료 저장</button>
          </div>
        )}
      </section>
    </div>
  );
}
