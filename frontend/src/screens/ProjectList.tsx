import { useEffect, useState } from "react";
import { api, messageOf, type AppStatus, type ProjectInfo } from "../api/client";

/** 상태 응답을 한 줄 문구로 바꾼다 (계획서 2026-09-01 태스크 4, 파일럿 관찰 5). */
export function describeStatus(status: AppStatus): string {
  const { login } = status;
  if (login.logged_in === true) {
    const last = status.last_generation_at
      ? status.last_generation_at.slice(0, 16).replace("T", " ")
      : "아직 없음";
    return `AI 연결: 로그인됨 (${login.auth_method ?? "방식 미상"}, ${login.account ?? "계정 미상"}). `
      + `마지막 생성 성공: ${last}`;
  }
  if (login.logged_in === false) {
    return "AI 연결: 로그인되지 않았습니다. 터미널에서 claude 명령으로 로그인한 뒤 "
      + "서버 창을 닫고 SlideCaptain실행.bat을 다시 실행해 주세요.";
  }
  const version = login.cli_version ? `, CLI ${login.cli_version}` : "";
  return `AI 연결: 확인하지 못했습니다 (${login.error ?? "원인 미상"}${version}).`;
}

export function ProjectList({ onOpen }: { onOpen: (p: ProjectInfo) => void }) {
  const [projects, setProjects] = useState<ProjectInfo[] | null>(null);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [statusLine, setStatusLine] = useState("AI 연결 상태를 확인하는 중...");

  useEffect(() => {
    api.listProjects().then(setProjects).catch((e) => setError(messageOf(e)));
    // 상태 조회 실패는 목록 표시를 막지 않는다 (오류 영역이 아니라 상태 줄에만 남긴다)
    api.getStatus()
      .then((s) => setStatusLine(describeStatus(s)))
      .catch(() => setStatusLine("AI 연결 상태를 불러오지 못했습니다."));
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
      <p className="ai-status">{statusLine}</p>
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
