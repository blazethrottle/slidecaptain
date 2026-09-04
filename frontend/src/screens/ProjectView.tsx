import { useEffect, useRef, useState } from "react";
import { setConsentPrompter } from "../api/aiGate";
import { api, messageOf, type Deck, type ProjectInfo } from "../api/client";
import { AiConsentDialog } from "./AiConsentDialog";
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
  // 자료 탭의 XLSX 업로드가 진행 중이다(계획서 B4 가정 7). generating과 합치지 않는다: 구조안 탭은
  // 생성 중에는 잠그지 않는 예외가 있는데, 업로드는 자료 탭 안의 일이라 구조안 탭까지 잠가야 FC-17이 막힌다
  const [uploading, setUploading] = useState(false);
  const [hasConflict, setHasConflict] = useState(false);  // 다른 창이나 프로그램이 먼저 저장해 412를 받았다
  // AI 전송 고지 대화 상자 (계획서 B3): 열려 있는 동안 사용자의 선택을 담을 resolve 함수를 들고 있는다.
  // null이 아니면 대화 상자가 열려 있다는 뜻이라 다른 상태와 함께 잠금 조건에도 쓴다
  const [consentResolve, setConsentResolve] = useState<((granted: boolean) => void) | null>(null);
  const flushScreen = useRef<null | (() => Promise<boolean>)>(null);
  // leaveScreen이 flush 실패의 일반 배너를 띄우기 전에 확인한다: onConflict가 이미 그 실패를
  // 설명했으면(플러시 도중 412) 중복 배너를 생략한다 (A5b 리뷰 발견 3)
  const justConflicted = useRef(false);

  useEffect(() => {
    if (project.status === "ok") {
      api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
    }
  }, [project.name, project.status]);

  // AI 전송 고지 관문(계획서 B3): 동의가 없는 상태에서 첫 AI 호출이 이 프롬프터를 부른다.
  // 대화 상자를 열고 사용자의 선택을 기다리는 프라미스를 돌려준다
  useEffect(() => {
    setConsentPrompter(() => new Promise<boolean>((resolve) => { setConsentResolve(() => resolve); }));
    return () => setConsentPrompter(null);
  }, []);

  const closeConsentDialog = (granted: boolean) => {
    consentResolve?.(granted);
    setConsentResolve(null);
  };

  // 편집 탭이나 자료 탭에 저장하지 않은 변경이 있거나, 업로드나 순차 생성이 진행 중이면 창 닫기(새로고침
  // 포함)를 막는다. 착지한 저장은 leaveScreen이 dirty를 내리므로 여기서는 자식이 보고하는 상태를 그대로
  // 반영한다. generating을 넣은 것은 이번 묶음의 보강이다: 종전에는 순차 생성 중 창을 닫아도 경고가
  // 없었다(계획서 B4 가정 7, 1차 리뷰)
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      // returnValue도 함께 설정한다: preventDefault만으로는 확인 대화를 띄우지 않는
      // 구형 구현이 있다 (A5b 리뷰 발견 5)
      if (dirty || uploading || generating) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty, uploading, generating]);

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
      // 이번 플러시 동안 생긴 충돌만 본다: 저장 버튼처럼 leaveScreen 밖에서 켜진 값이 새어 들어와
      // 무관한 실패의 배너까지 삼키지 않게 호출 직전에 재설정한다 (묶음 최종 리뷰 1)
      justConflicted.current = false;
      const flushed = await flushScreen.current();
      if (flushed) {
        setDirty(false);
      } else if (!justConflicted.current) {
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
  const onConflict = () => { justConflicted.current = true; setHasConflict(true); };
  // AI 전송 고지 대화 상자가 열린 동안은 leaving과 같은 조건으로 내비게이션을 잠근다 (계획서 B3)
  const dialogOpen = consentResolve !== null;
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
          {/* 다른 헤더 버튼과 같은 조건으로 잠근다: 업로드 진행 중 눌러 자료 화면이 통째로
              언마운트되면, 나중에 응답한 업로드 결과가 화면에 영구히 반영되지 않는다(B 묶음
              최종 리뷰 major F-1) */}
          <button onClick={reloadDeck} disabled={generating || uploading || leaving || dialogOpen}
            title={generating ? "AI 생성이 끝나면 다시 읽을 수 있습니다"
              : uploading ? "자료 업로드가 끝나면 다시 읽을 수 있습니다" : undefined}>서버 내용 다시 읽기</button>
        </p>
      )}
      <header>
        <button onClick={goBack} disabled={generating || uploading || leaving || dialogOpen}
          title={generating ? "AI 생성이 끝나면 이동할 수 있습니다"
            : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined}>목록으로</button>
        <h1>{deck.meta.title}</h1>
        <nav>
          <button aria-pressed={tab === "sources"} disabled={generating || uploading || leaving || dialogOpen}
            onClick={() => switchTab("sources")}
            title={generating ? "AI 생성이 끝나면 이동할 수 있습니다"
              : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined}>자료</button>
          {/* 구조안 탭은 generating으로는 잠그지 않는 예외지만(진행 표시가 그 화면에 있다), 업로드는
              자료 탭 안의 일이라 여기까지 잠가야 FC-17이 막힌다(계획서 B4 가정 7) */}
          <button aria-pressed={tab === "structure"} disabled={uploading || leaving || dialogOpen}
            onClick={() => switchTab("structure")}
            title={uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined}>구조안</button>
          <button aria-pressed={tab === "editor"}
            disabled={!hasSlides || generating || uploading || leaving || dialogOpen}
            onClick={() => switchTab("editor")}
            title={generating
              ? "AI 생성이 끝나면 이동할 수 있습니다"
              : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다"
              : hasSlides ? undefined : "구조안을 승인하고 내용을 생성하면 열립니다"}>편집</button>
          <button onClick={doExport}
            disabled={!hasSlides || exporting || generating || uploading || leaving || dialogOpen}
            title={generating ? "AI 생성이 끝나면 이동할 수 있습니다"
              : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined}>PPTX 내보내기</button>
          <button onClick={openRecovery} disabled={generating || uploading || leaving || dialogOpen}
            title={generating ? "AI 생성이 끝나면 이동할 수 있습니다"
              : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined}>스냅샷 복구</button>
        </nav>
      </header>
      {dialogOpen && (
        <AiConsentDialog onConfirm={() => closeConsentDialog(true)} onCancel={() => closeConsentDialog(false)} />
      )}
      {exportPath && <p className="export-path">내보내기 완료: {exportPath} (PowerPoint에서 여세요)</p>}
      {showRecovery && (
        <RecoveryScreen project={project} onConflict={onConflict} onBack={() => {
          setShowRecovery(false);
          // 412로 뜬 배너를 이 경로에서도 내린다: 아래에서 덱을 새로 읽으므로 이미 해소된
          // 상황이고, 그렇지 않으면 배너가 영구히 남는다 (A5b 리뷰 발견 2)
          setHasConflict(false);
          // 복원본을 다시 읽을 때까지 덱을 내린다: 옛 덱으로 편집기가 재마운트되어
          // 다음 자동 저장이 복원 결과를 덮어쓰는 사고를 막는다 (2026-08-29 적대 리뷰 반영)
          setDeck(null);
          api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
        }} />
      )}
      {!showRecovery && tab === "sources" && (
        <SourcesScreen project={project} deck={deck} onDeckChange={setDeck}
          onScreenReady={(f) => { flushScreen.current = f; }}
          onDirtyChange={setDirty} onConflict={onConflict} onBusyChange={setUploading} />
      )}
      {!showRecovery && tab === "structure" && (
        <StructureScreen project={project} deck={deck} onDeckChange={setDeck}
          onDone={() => setTab("editor")} onBusyChange={setGenerating} onConflict={onConflict} />
      )}
      {!showRecovery && tab === "editor" && hasSlides && (
        <EditorScreen project={project} deck={deck} onDeckChange={setDeck}
          onEditorReady={(f) => { flushScreen.current = f; }}
          onConflictHint={() => { justConflicted.current = true; }}
          onDirtyChange={setDirty} />
      )}
    </main>
  );
}
