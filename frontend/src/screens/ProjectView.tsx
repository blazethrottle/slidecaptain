import { useEffect, useRef, useState } from "react";
import { api, messageOf, type Deck, type ProjectInfo } from "../api/client";
import { EditorScreen } from "./EditorScreen";
import { RecoveryScreen } from "./RecoveryScreen";
import { SourcesScreen } from "./SourcesScreen";
import { StructureScreen } from "./StructureScreen";

export type Tab = "sources" | "structure" | "editor";

export function ProjectView({ project, onBack }: { project: ProjectInfo; onBack: () => void }) {
  const [deck, setDeck] = useState<Deck | null>(null);
  const [tab, setTab] = useState<Tab>("sources");
  const [error, setError] = useState("");
  const [exportPath, setExportPath] = useState("");
  const [exporting, setExporting] = useState(false);
  const [showRecovery, setShowRecovery] = useState(false);
  const [generating, setGenerating] = useState(false);  // 구조안 승인 후 장별 순차 생성 진행 중 (쓰기 포크 차단)
  const flushEditor = useRef<null | (() => Promise<boolean>)>(null);

  useEffect(() => {
    if (project.status === "ok") {
      api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
    }
  }, [project.name, project.status]);

  if (project.status === "needs_recovery") {
    return (
      <main>
        <h1>{project.title}</h1>
        <RecoveryScreen project={project} onBack={onBack} />
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

  // 탭 전환 전 편집기의 언마운트 플러시가 착지하길 기다린다: 그렇지 않으면 다음 탭(구조안 draft,
  // 자료 meta)이 낡은 덱으로 초기화되어 방금 한 편집이 되돌아가거나 잘못된 확인 대화가 뜬다
  // (2026-08-29 최종 리뷰 발견)
  const switchTab = async (t: Tab) => {
    if (flushEditor.current) {
      await flushEditor.current();
    }
    setTab(t);
  };

  const doExport = async () => {
    setExporting(true);
    setExportPath("");
    try {
      // 보류 중 자동 저장 플러시 (결정 1). 실패하면 마지막 편집이 빠진 채 내보내지므로 중단한다
      // (2026-08-29 태스크 16 리뷰 반영)
      const flushed = flushEditor.current ? await flushEditor.current() : true;
      if (!flushed) {
        setError("마지막 편집을 저장하지 못해 내보내기를 중단했습니다. 저장 상태를 확인한 뒤 다시 시도해 주세요.");
        return;
      }
      await api.createSnapshot(project.name);  // 내보내기 직전 복구 지점 (결정 1)
      const r = await api.exportDeck(project.name);
      setExportPath(r.path);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setExporting(false);
    }
  };

  return (
    <main className="project-view">
      {error && (
        <p role="alert">{error} <button onClick={() => setError("")}>닫기</button></p>
      )}
      <header>
        <button onClick={onBack}>목록으로</button>
        <h1>{deck.meta.title}</h1>
        <nav>
          <button aria-pressed={tab === "sources"} disabled={generating}
            onClick={() => switchTab("sources")}
            title={generating ? "AI 생성이 끝나면 이동할 수 있습니다" : undefined}>자료</button>
          <button aria-pressed={tab === "structure"} onClick={() => switchTab("structure")}>구조안</button>
          <button aria-pressed={tab === "editor"} disabled={!hasSlides || generating}
            onClick={() => switchTab("editor")}
            title={generating
              ? "AI 생성이 끝나면 이동할 수 있습니다"
              : hasSlides ? undefined : "구조안을 승인하고 내용을 생성하면 열립니다"}>편집</button>
          <button onClick={doExport} disabled={!hasSlides || exporting || generating}
            title={generating ? "AI 생성이 끝나면 이동할 수 있습니다" : undefined}>PPTX 내보내기</button>
          <button onClick={() => setShowRecovery(true)} disabled={generating}
            title={generating ? "AI 생성이 끝나면 이동할 수 있습니다" : undefined}>스냅샷 복구</button>
        </nav>
      </header>
      {exportPath && <p className="export-path">내보내기 완료: {exportPath} (PowerPoint에서 여세요)</p>}
      {showRecovery && (
        <RecoveryScreen project={project} onBack={() => {
          setShowRecovery(false);
          // 복원본을 다시 읽을 때까지 덱을 내린다: 옛 덱으로 편집기가 재마운트되어
          // 다음 자동 저장이 복원 결과를 덮어쓰는 사고를 막는다 (2026-08-29 적대 리뷰 반영)
          setDeck(null);
          api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
        }} />
      )}
      {!showRecovery && tab === "sources" && (
        <SourcesScreen project={project} deck={deck} onDeckChange={setDeck} />
      )}
      {!showRecovery && tab === "structure" && (
        <StructureScreen project={project} deck={deck} onDeckChange={setDeck}
          onDone={() => setTab("editor")} onBusyChange={setGenerating} />
      )}
      {!showRecovery && tab === "editor" && hasSlides && (
        <EditorScreen project={project} deck={deck} onDeckChange={setDeck}
          onEditorReady={(f) => { flushEditor.current = f; }} />
      )}
    </main>
  );
}
