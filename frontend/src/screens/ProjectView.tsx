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
  const [leaving, setLeaving] = useState(false);        // 화면 이탈 전 플러시 진행 중: 모든 이탈 경로 버튼을 잠근다
  const [dirty, setDirty] = useState(false);            // 편집 탭 또는 자료 탭에 저장하지 않은 변경이 있다 (beforeunload 경고용)
  const [hasConflict, setHasConflict] = useState(false);  // 다른 창이나 프로그램이 먼저 저장해 412를 받았다
  const flushScreen = useRef<null | (() => Promise<boolean>)>(null);

  useEffect(() => {
    if (project.status === "ok") {
      api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
    }
  }, [project.name, project.status]);

  // 편집 탭이나 자료 탭에 저장하지 않은 변경이 있으면 창 닫기(새로고침 포함)를 막는다.
  // 착지한 저장은 leaveScreen이 dirty를 내리므로 여기서는 자식이 보고하는 상태를 그대로 반영한다
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

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

  // 편집 탭이나 자료 탭을 떠나는 모든 경로(탭 전환, 목록으로, 스냅샷 복구, 내보내기)는 잔여 편집의 플러시가
  // 착지하길 기다리고, 실패하면 떠나지 않는다. 그렇지 않으면 다음 탭(구조안 draft, 자료 meta)이 낡은 덱으로
  // 초기화되거나(2026-08-29 최종 리뷰 발견), 언마운트 플러시의 실패가 이미 내려간 화면에 묻히거나(FC-08),
  // 복원 POST 뒤에 착지한 PUT 이 복원본을 덮는다(FC-11) (2026-09-03 저장 안전성 묶음). action 은 조사까지
  // 포함한다 ("이동을"). 플러시가 착지하면 미저장 변경이 없다는 뜻이므로 dirty를 여기서 내린다(FC-15 관련)
  const leaveScreen = async (action: string): Promise<boolean> => {
    if (!flushScreen.current) return true;
    setLeaving(true);
    try {
      const flushed = await flushScreen.current();
      if (flushed) {
        setDirty(false);
      } else {
        setError(`마지막 편집을 저장하지 못해 ${action} 중단했습니다. 저장 상태를 확인한 뒤 다시 시도해 주세요.`);
      }
      return flushed;
    } finally {
      setLeaving(false);
    }
  };

  const switchTab = async (t: Tab) => {
    if (await leaveScreen("이동을")) setTab(t);
  };
  const goBack = async () => {
    if (await leaveScreen("이동을")) onBack();
  };
  const openRecovery = async () => {
    if (await leaveScreen("이동을")) setShowRecovery(true);
  };

  const doExport = async () => {
    setExporting(true);
    setExportPath("");
    try {
      // 보류 중 자동 저장 플러시 (결정 1). 실패하면 마지막 편집이 빠진 채 내보내지므로 중단한다
      // (2026-08-29 태스크 16 리뷰 반영)
      if (!(await leaveScreen("내보내기를"))) return;
      await api.createSnapshot(project.name);  // 내보내기 직전 복구 지점 (결정 1)
      const r = await api.exportDeck(project.name);
      setExportPath(r.path);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setExporting(false);
    }
  };

  // 구조안, 자료, 복구 화면의 412는 전용 UI 없이 이 배너의 "서버 내용 다시 읽기"로 회복한다.
  // 편집 탭의 충돌은 EditorScreen 자체의 되돌리기 버튼이 처리하므로 onConflict를 넘기지 않는다
  const onConflict = () => setHasConflict(true);
  const reloadDeck = () => {
    setHasConflict(false);
    setDirty(false);  // 서버 내용으로 자식 화면을 다시 마운트하므로 미저장 변경이 없다
    setDeck(null);
    api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
  };

  return (
    <main className="project-view">
      {error && (
        <p role="alert">{error} <button onClick={() => setError("")}>닫기</button></p>
      )}
      {hasConflict && (
        <p role="alert">
          다른 창이나 프로그램에서 먼저 저장되었습니다.{" "}
          <button onClick={reloadDeck}>서버 내용 다시 읽기</button>
        </p>
      )}
      <header>
        <button onClick={goBack} disabled={generating || leaving}
          title={generating ? "AI 생성이 끝나면 이동할 수 있습니다" : undefined}>목록으로</button>
        <h1>{deck.meta.title}</h1>
        <nav>
          <button aria-pressed={tab === "sources"} disabled={generating || leaving}
            onClick={() => switchTab("sources")}
            title={generating ? "AI 생성이 끝나면 이동할 수 있습니다" : undefined}>자료</button>
          <button aria-pressed={tab === "structure"} disabled={leaving}
            onClick={() => switchTab("structure")}>구조안</button>
          <button aria-pressed={tab === "editor"} disabled={!hasSlides || generating || leaving}
            onClick={() => switchTab("editor")}
            title={generating
              ? "AI 생성이 끝나면 이동할 수 있습니다"
              : hasSlides ? undefined : "구조안을 승인하고 내용을 생성하면 열립니다"}>편집</button>
          <button onClick={doExport} disabled={!hasSlides || exporting || generating || leaving}
            title={generating ? "AI 생성이 끝나면 이동할 수 있습니다" : undefined}>PPTX 내보내기</button>
          <button onClick={openRecovery} disabled={generating || leaving}
            title={generating ? "AI 생성이 끝나면 이동할 수 있습니다" : undefined}>스냅샷 복구</button>
        </nav>
      </header>
      {exportPath && <p className="export-path">내보내기 완료: {exportPath} (PowerPoint에서 여세요)</p>}
      {showRecovery && (
        <RecoveryScreen project={project} onConflict={onConflict} onBack={() => {
          setShowRecovery(false);
          // 복원본을 다시 읽을 때까지 덱을 내린다: 옛 덱으로 편집기가 재마운트되어
          // 다음 자동 저장이 복원 결과를 덮어쓰는 사고를 막는다 (2026-08-29 적대 리뷰 반영)
          setDeck(null);
          api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
        }} />
      )}
      {!showRecovery && tab === "sources" && (
        <SourcesScreen project={project} deck={deck} onDeckChange={setDeck}
          onScreenReady={(f) => { flushScreen.current = f; }}
          onDirtyChange={setDirty} onConflict={onConflict} />
      )}
      {!showRecovery && tab === "structure" && (
        <StructureScreen project={project} deck={deck} onDeckChange={setDeck}
          onDone={() => setTab("editor")} onBusyChange={setGenerating} onConflict={onConflict} />
      )}
      {!showRecovery && tab === "editor" && hasSlides && (
        <EditorScreen project={project} deck={deck} onDeckChange={setDeck}
          onEditorReady={(f) => { flushScreen.current = f; }}
          onDirtyChange={setDirty} />
      )}
    </main>
  );
}
