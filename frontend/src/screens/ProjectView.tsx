import { useEffect, useState } from "react";
import { api, messageOf, type Deck, type ProjectInfo } from "../api/client";
import { SourcesScreen } from "./SourcesScreen";

export type Tab = "sources" | "structure" | "editor";

export function ProjectView({ project, onBack }: { project: ProjectInfo; onBack: () => void }) {
  const [deck, setDeck] = useState<Deck | null>(null);
  const [tab, setTab] = useState<Tab>("sources");
  const [error, setError] = useState("");

  useEffect(() => {
    if (project.status === "ok") {
      api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
    }
  }, [project.name, project.status]);

  if (project.status === "needs_recovery") {
    // 복구 화면은 Task 16이 교체한다. 그때까지는 안내만 한다
    return (
      <main>
        <p role="alert">이 프로젝트는 복구가 필요합니다. 스냅샷 복구 화면에서 이전 저장 시점으로 되돌릴 수 있습니다.</p>
        <button onClick={onBack}>목록으로</button>
      </main>
    );
  }
  if (deck === null) {
    // 최초 로드 실패만 화면 전체를 대체한다. 로드 이후의 오류(내보내기 실패 등)는
    // 아래 배너로 표시해 편집 맥락을 잃지 않는다 (2026-08-29 적대 리뷰 반영)
    return (
      <main>
        {error ? (
          <>
            <p role="alert">{error}</p>
            <button onClick={onBack}>목록으로</button>
          </>
        ) : (
          <p>불러오는 중...</p>
        )}
      </main>
    );
  }

  const hasSlides = deck.slides.length > 0;
  return (
    <main className="project-view">
      {error && (
        <p role="alert">{error} <button onClick={() => setError("")}>닫기</button></p>
      )}
      <header>
        <button onClick={onBack}>목록으로</button>
        <h1>{deck.meta.title}</h1>
        <nav>
          <button aria-pressed={tab === "sources"} onClick={() => setTab("sources")}>자료</button>
          <button aria-pressed={tab === "structure"} disabled>구조안</button>
          <button aria-pressed={tab === "editor"} disabled={!hasSlides}
            title={hasSlides ? undefined : "구조안을 승인하고 내용을 생성하면 열립니다"}>편집</button>
        </nav>
      </header>
      {tab === "sources" && <SourcesScreen project={project} deck={deck} onDeckChange={setDeck} />}
    </main>
  );
}
