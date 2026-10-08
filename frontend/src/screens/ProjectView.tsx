import { useCallback, useEffect, useRef, useState } from "react";
import { setConsentPrompter } from "../api/aiGate";
import { api, messageOf, savedEtag, type ActiveJob, type AppStatus, type Deck, type ExportResult, type ProjectInfo } from "../api/client";
import { AISettingsPanel } from "./AISettingsPanel";
import { AiConsentDialog } from "./AiConsentDialog";
import { EditorScreen } from "./EditorScreen";
import { ExportQualitySummary } from "./ExportQualitySummary";
import { ExportHistoryPanel } from "./ExportHistoryPanel";
import { RecoveryScreen } from "./RecoveryScreen";
import { JobAnnouncer, StatusIndicator } from "../ui/StatusIndicator";
import { SourcesScreen } from "./SourcesScreen";
import { StructureScreen } from "./StructureScreen";

export type Tab = "sources" | "structure" | "editor" | "history";

export function ProjectView({ project, onBack, jobPollMs = 1000 }: {
  project: ProjectInfo; onBack: () => void; jobPollMs?: number;
}) {
  const [deck, setDeck] = useState<Deck | null>(null);
  const [tab, setTab] = useState<Tab>("sources");
  const [error, setError] = useState("");
  const [exportResult, setExportResult] = useState<{ projectName: string; result: ExportResult } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [showRecovery, setShowRecovery] = useState(false);
  const [generating, setGenerating] = useState(false);  // 구조안 승인 후 장별 순차 생성 진행 중 (쓰기 포크 차단)
  const [diagramGenerating, setDiagramGenerating] = useState(false);
  const [leaving, setLeaving] = useState(false);        // 화면 이탈 전 플러시 진행 중: 모든 이탈 경로 버튼을 잠근다
  const [dirty, setDirty] = useState(false);            // 현재 화면에 저장하지 않은 변경이 있다 (beforeunload 경고용)
  // 자료 탭의 XLSX 업로드가 진행 중이다(계획서 B4 가정 7). generating과 합치지 않는다: 구조안 탭은
  // 생성 중에는 잠그지 않는 예외가 있는데, 업로드는 자료 탭 안의 일이라 구조안 탭까지 잠가야 FC-17이 막힌다
  const [uploading, setUploading] = useState(false);
  const [hasConflict, setHasConflict] = useState(false);  // 다른 창이나 프로그램이 먼저 저장해 412를 받았다
  // AI 전송 고지 대화 상자 (계획서 B3): 열려 있는 동안 사용자의 선택을 담을 resolve 함수를 들고 있는다.
  // null이 아니면 대화 상자가 열려 있다는 뜻이라 다른 상태와 함께 잠금 조건에도 쓴다
  const [consentResolve, setConsentResolve] = useState<((granted: boolean) => void) | null>(null);
  const [consentStatus, setConsentStatus] = useState<AppStatus | undefined>(undefined);
  const flushScreen = useRef<null | (() => Promise<boolean>)>(null);
  // leaveScreen이 flush 실패의 일반 배너를 띄우기 전에 확인한다: onConflict가 이미 그 실패를
  // 설명했으면(플러시 도중 412) 중복 배너를 생략한다 (A5b 리뷰 발견 3)
  const justConflicted = useRef(false);
  // 서비스 전체의 진행 중 AI 작업 (D2b-5a, 계획서 5.9). 확인 전에는 생성 중과 같이 잠근다(새로고침 직후 잠금 공백 방지)
  const [jobChecked, setJobChecked] = useState(false);
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  const [ledgerAvailable, setLedgerAvailable] = useState(true);
  const checkSeq = useRef(0);
  const checkedOnce = useRef(false);
  const refreshActiveJob = useCallback(async () => {
    const seq = ++checkSeq.current;
    try {
      const status = await api.getActiveJob();
      if (seq !== checkSeq.current) return;  // 늦게 온 옛 응답은 버린다 (D2b-5a 리뷰 R18)
      setActiveJob(status.active ?? null);
      setLedgerAvailable(status.ledger_available);
    } catch {
      if (seq !== checkSeq.current) return;
      // 첫 확인이 실패하면 잠그지 않는다(생성 버튼이 원인을 안내한다). 진행 중으로 확인한 작업은 놓지 않고
      // 새 객체로 바꿔 다음 조회를 예약한다 (D2b-5a 리뷰 R4)
      setActiveJob((previous) => (previous ? { ...previous } : null));
    } finally {
      if (seq === checkSeq.current) { setJobChecked(true); checkedOnce.current = true; }
    }
  }, []);
  useEffect(() => {
    void refreshActiveJob();
    const onFocus = () => void refreshActiveJob();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refreshActiveJob]);
  // 진행 중 작업이 있는 동안만 다시 확인한다
  useEffect(() => {
    if (!activeJob) return;
    const timer = setTimeout(() => void refreshActiveJob(), jobPollMs);
    return () => clearTimeout(timer);
  }, [activeJob, jobPollMs, refreshActiveJob]);
  const batchHere = activeJob?.project === project.name && activeJob.kind === "chapters";
  // 이 프로젝트를 열 때 이미 묶음이 돌고 있으면 진행 표시가 있는 구조안 탭을 연다. 그 뒤에 나타난 묶음은
  // 편집 탭의 저장을 거치지 않고 탭을 바꾸지 않도록 안내만 한다 (D2b-5a 리뷰 R3, R18)
  const openedWithBatch = useRef<boolean | null>(null);
  useEffect(() => {
    if (!jobChecked || openedWithBatch.current !== null) return;
    openedWithBatch.current = batchHere;
    if (batchHere) setTab("structure");
  }, [jobChecked, batchHere]);
  // 묶음이 끝났는데 이 탭이 본 저장본이 서버와 다르면(구조안 화면이 따라가지 못했거나 다른 탭의 묶음):
  // 구조안 탭이면 덱을 다시 읽고, 편집 탭이면 덮어쓰지 않도록 충돌 안내로 다시 읽기를 맡긴다.
  // 편집기는 덱을 마운트 때만 받으므로 저장 ETag만 새로 읽으면 옛 내용으로 묶음의 장을 덮는다 (D2b-5a 리뷰 R5, β 리뷰 R1)
  const wasBatchHere = useRef(false);
  const tabRef = useRef(tab);
  tabRef.current = tab;
  useEffect(() => {
    if (wasBatchHere.current && !batchHere) {
      api.getDocumentChangeBasis(project.name).then((basis) => {
        if (basis.base_etag === savedEtag(project.name)) return;  // 이 탭이 이미 따라갔다
        if (tabRef.current === "structure") api.getDeck(project.name).then(setDeck).catch(() => {});
        else setHasConflict(true);
      }).catch(() => {});
    }
    wasBatchHere.current = batchHere;
  }, [batchHere, project.name]);
  // 화면 전체를 막는 AI 작업: 구조안 승인의 장 생성, 도식 생성, 진행 중 작업 확인 전, 이 프로젝트의 장 생성 묶음
  const aiBusy = generating || diagramGenerating || !jobChecked || batchHere;
  const aiBusyTitle = !jobChecked ? "작업 상태를 확인하는 중입니다" : "AI 생성이 끝나면 이동할 수 있습니다";

  useEffect(() => {
    if (project.status === "ok") {
      api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
    }
  }, [project.name, project.status]);

  // AI 전송 고지 관문(계획서 B3): 동의가 없는 상태에서 첫 AI 호출이 이 프롬프터를 부른다.
  // 대화 상자를 열고 사용자의 선택을 기다리는 프라미스를 돌려준다
  useEffect(() => {
    setConsentPrompter((status) => new Promise<boolean>((resolve) => {
      setConsentStatus(status); setConsentResolve(() => resolve);
    }));
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
      // 독립 앱에서는 진행 중 AI 작업을 main 프로세스가 "계속 작업 / 취소 후 닫기"로 묻는다. 여기서 또 막으면
      // 취소한 뒤에도 같은 대화 상자가 한 번 더 뜬다 (D2b-5c 리뷰 R3). 웹 모드는 이 경고가 유일한 안내다
      const aiRunning = !window.slidecaptain && (generating || diagramGenerating || batchHere);
      if (dirty || uploading || aiRunning) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty, uploading, generating, diagramGenerating, batchHere]);

  if (project.status === "newer_format") {
    // 이 앱이 모르는 형식이다. 모르는 필드를 버린 채 열거나 내보내지 않도록 아무 것도 읽지 않는다 (D2a-1)
    return (
      <main>
        <h1>{project.name}</h1>
        <p role="alert">
          이 프로젝트는 더 새 버전의 SlideCaptain이 만든 프로젝트입니다. 이 버전에서는 열 수 없습니다.
          프로젝트 파일은 바꾸지 않았습니다. 새 버전의 앱으로 열어 주세요.
        </p>
        <button onClick={onBack}>목록으로</button>
      </main>
    );
  }

  if (project.status === "unreadable_manifest") {
    // 형식 기록을 덮어쓰면 이후 앱의 기록이 사라지므로 열지 않는다 (D2a-1 리뷰 R2)
    return (
      <main>
        <h1>{project.name}</h1>
        <p role="alert">
          이 프로젝트의 형식 기록 파일(manifest.json)을 읽지 못했습니다. 기록을 지우지 않도록 프로젝트를
          열지 않았습니다. 새 버전의 앱으로 열거나, 파일을 다른 곳에 보관한 뒤 지우면 다시 열 수 있습니다.
        </p>
        <button onClick={onBack}>목록으로</button>
      </main>
    );
  }

  if (project.status === "needs_recovery") {
    return (
      <main>
        <h1>{project.title}</h1>
        <RecoveryScreen project={project} onBack={onBack} />
        <ExportHistoryPanel projectName={project.name} readOnly />
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
            <ExportHistoryPanel projectName={project.name} readOnly />
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
      } else if (!justConflicted.current && tab !== "history") {
        setError(`마지막 편집을 저장하지 못해 ${action} 중단했습니다. 저장 상태를 확인한 뒤 다시 시도해 주세요.`);
      }
      return flushed;
    } finally {
      setLeaving(false);
    }
  };

  const switchTab = async (t: Tab) => {
    if (await leaveScreen("이동을")) {
      setError("");
      setTab(t);
    }
  };
  const goBack = async () => {
    if (await leaveScreen("이동을")) onBack();
  };
  const openRecovery = async () => {
    if (await leaveScreen("이동을")) setShowRecovery(true);
  };

  const doExport = async () => {
    setExporting(true);
    setExportResult(null);
    try {
      // 보류 중 자동 저장 플러시 (결정 1). 실패하면 마지막 편집이 빠진 채 내보내지므로 중단한다
      // (2026-08-29 태스크 16 리뷰 반영)
      if (!(await leaveScreen("내보내기를"))) return;
      await api.createSnapshot(project.name);  // 내보내기 직전 복구 지점 (결정 1)
      const r = await api.exportDeck(project.name);
      setExportResult({ projectName: project.name, result: r });
      setHistoryRevision(value => value + 1);
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
  const reloadDeck = async () => {
    if (tab === "history" && !(await leaveScreen("다시 읽기를"))) return;
    // 자료와 구조안 화면의 폼 입력은 덱이 아니어서 보존하지 않는다. 버리기 전에 확인한다 (D2a-2)
    if (dirty && !window.confirm("저장하지 않은 입력이 사라집니다. 필요한 내용은 먼저 복사해 두세요. 서버 내용을 다시 읽을까요?")) return;
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
          <button onClick={reloadDeck} disabled={aiBusy || uploading || leaving || dialogOpen}
            title={aiBusy ? "AI 생성이 끝나면 다시 읽을 수 있습니다"
              : uploading ? "자료 업로드가 끝나면 다시 읽을 수 있습니다" : undefined}>서버 내용 다시 읽기</button>
        </p>
      )}
      <header>
        <button onClick={goBack} disabled={aiBusy || uploading || leaving || dialogOpen}
          title={aiBusy ? aiBusyTitle
            : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined}>목록으로</button>
        <h1>{deck.meta.title}</h1>
        <nav>
          <button aria-pressed={tab === "sources"} disabled={aiBusy || uploading || leaving || dialogOpen}
            onClick={() => switchTab("sources")}
            title={aiBusy ? aiBusyTitle
              : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined}>자료</button>
          {/* 구조안 탭은 generating으로는 잠그지 않는 예외지만(진행 표시가 그 화면에 있다), 업로드는
              자료 탭 안의 일이라 여기까지 잠가야 FC-17이 막힌다(계획서 B4 가정 7) */}
          <button aria-pressed={tab === "structure"} disabled={diagramGenerating || uploading || leaving || dialogOpen}
            onClick={() => switchTab("structure")}
            title={diagramGenerating ? "AI 생성이 끝나면 이동할 수 있습니다"
              : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined}>구조안</button>
          <button aria-pressed={tab === "editor"}
            disabled={aiBusy || uploading || leaving || dialogOpen}
            onClick={() => switchTab("editor")}
            title={aiBusy
              ? aiBusyTitle
              : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다"
              : hasSlides ? undefined : "도식을 직접 작성할 수 있습니다"}>편집</button>
          <button onClick={doExport}
            disabled={!hasSlides || exporting || aiBusy || uploading || leaving || dialogOpen}
            title={aiBusy ? aiBusyTitle
              : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : "내용과 시각 품질을 검수하지 않은 초안으로 내보냅니다"}>초안 PPTX 내보내기</button>
          <button onClick={openRecovery} disabled={aiBusy || uploading || leaving || dialogOpen}
            title={aiBusy ? aiBusyTitle
              : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined}>스냅샷 복구</button>
          <button aria-pressed={!showRecovery && tab === "history"} onClick={() => switchTab("history")}
            disabled={showRecovery || exporting || aiBusy || uploading || leaving || dialogOpen}
            title={showRecovery ? "복구 화면의 목록으로 버튼을 눌러 닫으면 이력을 열 수 있습니다" : undefined}>검수 이력</button>
        </nav>
      </header>
      {activeJob && (
        // 서비스 전체에서 하나만 도는 AI 작업의 안내와 취소. 이 프로젝트의 작업도 보인다 (D2b-5a 리뷰 R14, R21)
        <p className="notice">
          <StatusIndicator kind={activeJob.cancel_requested ? "cancel_requested" : "running"} />{" "}
          {activeJob.project === project.name
            ? "이 프로젝트에서 AI 생성이 진행 중입니다."
            : `다른 프로젝트(${activeJob.project})에서 AI 생성이 진행 중입니다. 끝난 뒤 생성할 수 있습니다.`}{" "}
          <button onClick={() => void api.cancelJob(activeJob.project, activeJob.id).then(refreshActiveJob)
            .catch((e) => setError(messageOf(e)))} disabled={activeJob.cancel_requested}>그 작업 취소</button>
        </p>
      )}
      <JobAnnouncer active={activeJob} />
      {!ledgerAvailable && (
        // 원장을 열 수 없으면 AI 생성만 막힌다 (계획서 D2b-5c)
        <p className="notice">작업 기록을 열 수 없어 AI 생성을 쓸 수 없습니다. 편집과 내보내기는 계속할 수 있습니다.</p>
      )}
      <AISettingsPanel disabled={aiBusy || uploading || leaving || dialogOpen} />
      {dialogOpen && (
        <AiConsentDialog statusSnapshot={consentStatus} onConfirm={() => closeConsentDialog(true)} onCancel={() => closeConsentDialog(false)} />
      )}
      <p className="quality-notice">현재 산출물은 검수 전 초안입니다. 보고 흐름, 근거와 실제 PowerPoint 표시를 확인한 뒤 제출해 주세요.</p>
      {exportResult?.projectName === project.name && <ExportQualitySummary result={exportResult.result} />}
      {showRecovery && (
        <RecoveryScreen project={project} onConflict={onConflict} onOpen={(next) => {
          // 복구 화면에서 처분한 뒤 옮기므로 덱을 다시 읽는다 (D2b-5c 리뷰 R16)
          setShowRecovery(false);
          setHasConflict(false);
          setDeck(null);
          api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
          setTab(next);
        }} onBack={() => {
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
          onDone={() => setTab("editor")} onBusyChange={setGenerating} onConflict={onConflict}
          onScreenReady={f => { flushScreen.current = f; }} onDirtyChange={setDirty} />
      )}
      {!showRecovery && tab === "editor" && (
        <EditorScreen project={project} deck={deck} onDeckChange={setDeck}
          onEditorReady={(f) => { flushScreen.current = f; }}
          onConflictHint={() => { justConflicted.current = true; }}
          onDirtyChange={setDirty} onBusyChange={setDiagramGenerating} />
      )}
      {!showRecovery && tab === "history" && <ExportHistoryPanel key={historyRevision} projectName={project.name} busy={exporting}
        onScreenReady={guard => { flushScreen.current = guard; }} onDirtyChange={setDirty} />}
    </main>
  );
}
