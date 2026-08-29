import { useEffect, useState } from "react";
import { api, messageOf, type ProjectInfo } from "../api/client";

export function ProjectList({ onOpen }: { onOpen: (p: ProjectInfo) => void }) {
  const [projects, setProjects] = useState<ProjectInfo[] | null>(null);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.listProjects().then(setProjects).catch((e) => setError(messageOf(e)));
  }, []);

  const create = async () => {
    setError("");
    try {
      onOpen(await api.createProject(name.trim(), title.trim()));
    } catch (e) {
      setError(messageOf(e));
    }
  };

  return (
    <main className="project-list">
      <h1>Slide Captain</h1>
      {error && <p role="alert">{error}</p>}
      <section>
        <h2>새 프로젝트</h2>
        <input aria-label="프로젝트 이름" placeholder="프로젝트 이름"
          value={name} onChange={(e) => setName(e.target.value)} />
        <input aria-label="보고서 제목" placeholder="보고서 제목 (비우면 이름과 같음)"
          value={title} onChange={(e) => setTitle(e.target.value)} />
        <button onClick={create} disabled={!name.trim()}>만들기</button>
      </section>
      <section>
        <h2>프로젝트</h2>
        {projects === null ? (
          <p>불러오는 중...</p>
        ) : projects.length === 0 ? (
          <p>아직 프로젝트가 없습니다. 위에서 새로 만들어 주세요.</p>
        ) : (
          <ul>
            {projects.map((p) => (
              <li key={p.name}>
                <button onClick={() => onOpen(p)}>
                  {p.title} <small>({p.name}, {p.updated_at})</small>
                  {p.status === "needs_recovery" && <em> 복구 필요</em>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
