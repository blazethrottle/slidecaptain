import { useEffect, useState } from "react";
import { api, messageOf, type Deck, type ProjectInfo } from "../api/client";

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
