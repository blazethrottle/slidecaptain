import { useCallback, useEffect, useRef, useState } from "react";
import { setConsentPrompter } from "../api/aiGate";
import { api, ApiError, messageOf, savedEtag, type ActiveJob, type AppStatus, type Deck, type ExportResult, type ProjectInfo } from "../api/client";
import { AISettingsPanel } from "./AISettingsPanel";
import { AiConsentDialog } from "./AiConsentDialog";
import { EditorScreen } from "./EditorScreen";
import { ExportHistoryPanel } from "./ExportHistoryPanel";
import { RecoveryScreen } from "./RecoveryScreen";
import { ReportPurposeScreen } from "./ReportPurposeScreen";
import { ReviewScreen } from "./ReviewScreen";
import { AiStatusLine } from "../ui/AiStatusLine";
import { JobAnnouncer, SaveAnnouncer, StatusIndicator, type SaveStatus } from "../ui/StatusIndicator";
import { SourcesScreen } from "./SourcesScreen";
import { StructureScreen } from "./StructureScreen";

// 다섯 단계 (개정판 D3a-2, 계획 4.1, 제품 설계 3절). 단계 화면은 전환 때 언마운트한다: 숨긴 채 마운트를
// 유지하면 화면이 옛 사본을 든 채 전역 저장 ETag만 새로 바뀌는 이음매(계획 사실 14, 15)가 다시 생긴다
export type Stage = "purpose" | "sources" | "structure" | "editor" | "review";
export const STAGES: ReadonlyArray<{ id: Stage; label: string }> = [
  { id: "purpose", label: "보고 목적" },
  { id: "sources", label: "자료" },
  { id: "structure", label: "구성" },
  { id: "editor", label: "편집" },
  { id: "review", label: "검토와 내보내기" },
];
// 덱의 사본을 들고 저장하는 단계. 묶음 종결 뒤 미저장 사본이 있으면 충돌 안내, 없으면 새 덱으로 다시 마운트한다.
// 자료와 검토 단계는 덱을 읽기만 하므로 덱만 다시 읽는다 (계획 4.1 β R1 분기)
const DECK_COPY_STAGES: ReadonlySet<Stage> = new Set(["purpose", "structure", "editor"]);
type Conflict = null | "other" | "batch_here";

export function ProjectView({ project, onBack, jobPollMs = 1000 }: {
  project: ProjectInfo; onBack: () => void; jobPollMs?: number;
}) {
  const [deck, setDeck] = useState<Deck | null>(null);
  // 처음 여는 단계는 보고 목적이다. 제품 설계에 첫 화면 지정이 없어 단계 순서의 첫 단계를 골랐다 (D3a-2 구현 기록)
  const [stage, setStage] = useState<Stage>("purpose");
  const [screenKey, setScreenKey] = useState(0);  // 늘리면 지금 단계 화면을 새 덱으로 다시 마운트한다
  const [error, setError] = useState("");
  const [exportResult, setExportResult] = useState<{ projectName: string; result: ExportResult } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [showRecovery, setShowRecovery] = useState(false);
  // 복구 화면에서 "현재 입력으로 다시 생성"으로 옮긴 장. 옮긴 단계에서 그 장을 미리 고른다 (C24)
  const [focusChapter, setFocusChapter] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);  // 구조안 승인 후 장별 순차 생성 진행 중 (쓰기 포크 차단)
  const [diagramGenerating, setDiagramGenerating] = useState(false);
  const [leaving, setLeaving] = useState(false);        // 화면 이탈 전 플러시 진행 중: 모든 이탈 경로 버튼을 잠근다
  const [dirty, setDirty] = useState(false);            // 현재 화면에 저장하지 않은 변경이 있다 (beforeunload 경고용)
  // 자료 단계의 XLSX 업로드가 진행 중이다(계획서 B4 가정 7). generating과 합치지 않는다: 구성 단계는
  // 생성 중에는 잠그지 않는 예외가 있는데, 업로드는 자료 단계 안의 일이라 구성 단계까지 잠가야 FC-17이 막힌다
  const [uploading, setUploading] = useState(false);
  const [conflict, setConflict] = useState<Conflict>(null);  // 다른 창이나 프로그램, 또는 묶음이 먼저 저장했다
  const [saveStatus, setSaveStatus] = useState<SaveStatus>(null);  // 상단 머리의 저장 상태 (계획 4.1 출처 표)
  const [draftCount, setDraftCount] = useState(0);  // 충돌로 보존한 변경 건수 (C18)
  const [draftsRevision, setDraftsRevision] = useState(0);
  const saveStatusRef = useRef<HTMLSpanElement | null>(null);
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
  // 이 프로젝트를 열 때 이미 묶음이 돌고 있으면 진행 표시가 있는 구성 단계를 연다. 그 뒤에 나타난 묶음은
  // 편집 단계의 저장을 거치지 않고 단계를 바꾸지 않도록 안내만 한다 (D2b-5a 리뷰 R3, R18)
  const openedWithBatch = useRef<boolean | null>(null);
  useEffect(() => {
    if (!jobChecked || openedWithBatch.current !== null) return;
    openedWithBatch.current = batchHere;
    if (batchHere) setStage("structure");
  }, [jobChecked, batchHere]);
  // 이 탭이 등록한 묶음의 작업 ID. 묶음 종결 뒤 충돌 안내를 사실에 맞게 쓴다 (계획 4.1)
  const startedHere = useRef<Set<string>>(new Set());
  const onJobRegistered = useCallback((id: string) => { startedHere.current.add(id); }, []);
  // 묶음이 끝났는데 이 탭이 본 저장본이 서버와 다르면(이 탭의 화면이 따라가지 못했거나 다른 탭의 묶음),
  // 지금 단계가 덱의 미저장 사본을 들고 있으면 덮어쓰지 않도록 충돌 안내로 다시 읽기를 맡기고, 들고 있지
  // 않으면 새 덱으로 다시 마운트한다. 덱을 읽기만 하는 단계는 덱만 다시 읽는다. 단계 화면은 덱을 마운트 때만
  // 받으므로 저장 ETag만 새로 읽으면 옛 사본으로 묶음의 장을 덮는다 (D2b-5a 리뷰 R5, β 리뷰 R1, 계획 4.1)
  const wasBatchHere = useRef(false);
  const lastBatchId = useRef<string | null>(null);
  const stageRef = useRef(stage);
  stageRef.current = stage;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const showRecoveryRef = useRef(showRecovery);
  showRecoveryRef.current = showRecovery;
  useEffect(() => {
    if (wasBatchHere.current && !batchHere) {
      const endedJob = lastBatchId.current;
      // 기준 조회는 이 탭의 저장 ETag를 If-Match로 보낸다. 같으면 200(이 탭이 이미 따라갔다), 다르면 412다.
      // 다른 실패는 판정하지 않고 다음 저장의 충돌 검사에 맡긴다 (β 리뷰 R1)
      api.getDocumentChangeBasis(project.name)
        .then((basis) => basis.base_etag !== savedEtag(project.name))
        .catch((e) => e instanceof ApiError && e.status === 412)
        .then((changed) => {
          if (!changed) return;
          const holdsCopy = !showRecoveryRef.current && DECK_COPY_STAGES.has(stageRef.current);
          if (holdsCopy && dirtyRef.current) {
            setConflict(endedJob !== null && startedHere.current.has(endedJob) ? "batch_here" : "other");
            return;
          }
          api.getDeck(project.name).then((fresh) => {
            setDeck(fresh);
            if (holdsCopy) setScreenKey((k) => k + 1);  // 사본까지 새 덱으로 만든다
          }).catch(() => {});
        });
    }
    wasBatchHere.current = batchHere;
    if (batchHere && activeJob) lastBatchId.current = activeJob.id;
  }, [batchHere, activeJob, project.name]);
  // 화면 전체를 막는 AI 작업: 구조안 승인의 장 생성, 도식 생성, 진행 중 작업 확인 전, 이 프로젝트의 장 생성 묶음.
  // 생성 중 이동과 편집의 허용(계획 4.4)은 D3a-5가 한다
  const aiBusy = generating || diagramGenerating || !jobChecked || batchHere;
  const aiBusyTitle = !jobChecked ? "작업 상태를 확인하는 중입니다" : "AI 생성이 끝나면 이동할 수 있습니다";

  useEffect(() => {
    if (project.status === "ok") {
      api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
    }
  }, [project.name, project.status]);

  // 보존한 변경 건수 (C18). 단계를 옮기거나 복구 화면을 닫거나 편집 화면이 새로 보존하면 다시 센다
  useEffect(() => {
    if (project.status !== "ok") return;
    let cancelled = false;
    api.listDrafts(project.name)
      .then((list) => { if (!cancelled) setDraftCount(list.length); })
      .catch(() => { if (!cancelled) setDraftCount(0); });  // 낡은 건수를 남기지 않는다 (D2a-5 리뷰 R12)
    return () => { cancelled = true; };
  }, [project.name, project.status, stage, showRecovery, draftsRevision]);
  const onDraftsChanged = useCallback(() => setDraftsRevision((n) => n + 1), []);
  const focusSaveStatus = useCallback(() => saveStatusRef.current?.focus(), []);
  // 검토 단계의 저장 상태: 검수 기록 폼에 저장하지 않은 입력이 있으면 그 상태, 없으면 표시하지 않는다 (계획 4.1)
  const onReviewDirty = useCallback((d: boolean) => {
    setDirty(d);
    setSaveStatus(d ? { kind: "unsaved", detail: "검수 기록" } : null);
  }, []);

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

  // 지금 단계에 저장하지 않은 변경이 있거나, 업로드나 순차 생성이 진행 중이면 창 닫기(새로고침
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

  // 덱을 열 수 없는 상태는 다섯 단계 셸을 띄우지 않고 지금 화면을 유지한다 (계획 4.1)
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

  // 지금 단계를 떠나는 모든 경로(단계 이동, 목록으로, 스냅샷 복구, 내보내기)는 잔여 편집의 플러시가
  // 착지하길 기다리고, 실패하면 떠나지 않는다. 그렇지 않으면 다음 단계(구성 초안, 보고 정보)가 낡은 덱으로
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
      } else if (!justConflicted.current && stage !== "review") {
        setError(`마지막 편집을 저장하지 못해 ${action} 중단했습니다. 저장 상태를 확인한 뒤 다시 시도해 주세요.`);
      }
      return flushed;
    } finally {
      setLeaving(false);
    }
  };

  // 복구 화면을 닫고 단계로 간다. 복구 화면에서 처분했을 수 있으므로 덱을 다시 읽는다 (D2b-5c 리뷰 R16).
  // 복원본을 다시 읽을 때까지 덱을 내린다: 옛 덱으로 편집기가 재마운트되어 다음 자동 저장이 복원 결과를
  // 덮어쓰는 사고를 막는다 (2026-08-29 적대 리뷰 반영). 412로 뜬 안내도 내린다(A5b 리뷰 발견 2)
  const closeRecovery = (next?: Stage, chapterId?: string) => {
    setShowRecovery(false);
    setConflict(null);
    setDeck(null);
    api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
    setFocusChapter(chapterId ?? null);
    if (next) setStage(next);
  };

  const switchStage = async (next: Stage) => {
    // 복구 화면은 단계가 아니다. 단계를 고르면 복구 화면을 닫고 그 단계로 간다 (계획 4.1).
    // 복구 화면에는 이탈 확인이 없다(복원과 지우기는 각각 확인 창을 거친다)
    if (showRecovery) { closeRecovery(next); return; }
    if (next === stage) return;  // 지금 단계를 다시 고르면 아무것도 하지 않는다(화면이 다시 마운트되지 않아 저장 상태를 다시 올리지 않는다)
    if (await leaveScreen("이동을")) {
      setError("");
      setSaveStatus(null);
      setFocusChapter(null);
      setStage(next);
    }
  };
  const goBack = async () => {
    if (await leaveScreen("이동을")) onBack();
  };
  const openRecovery = async () => {
    if (await leaveScreen("이동을")) { setSaveStatus(null); setShowRecovery(true); }
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

  // 구성, 보고 목적, 복구 화면의 412는 전용 UI 없이 이 안내의 "서버 내용 다시 읽기"로 회복한다.
  // 편집 단계의 충돌은 EditorScreen 자체의 되돌리기 버튼이 처리하므로 onConflict를 넘기지 않는다
  const onConflict = () => { justConflicted.current = true; setConflict("other"); };
  // AI 전송 고지 대화 상자가 열린 동안은 leaving과 같은 조건으로 내비게이션을 잠근다 (계획서 B3)
  const dialogOpen = consentResolve !== null;
  const reloadDeck = async () => {
    if (stage === "review" && !(await leaveScreen("다시 읽기를"))) return;
    // 보고 목적과 구성 화면의 폼 입력은 덱이 아니어서 보존하지 않는다. 버리기 전에 확인한다 (D2a-2)
    if (dirty && !window.confirm("저장하지 않은 입력이 사라집니다. 필요한 내용은 먼저 복사해 두세요. 서버 내용을 다시 읽을까요?")) return;
    setConflict(null);
    setDirty(false);  // 서버 내용으로 자식 화면을 다시 마운트하므로 미저장 변경이 없다
    setDeck(null);
    api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
  };

  const locked = aiBusy || uploading || leaving || dialogOpen;
  const lockedTitle = aiBusy ? aiBusyTitle : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined;
  // 구성 단계는 generating으로는 잠그지 않는 예외다(진행 표시가 그 화면에 있다). 업로드는 자료 단계 안의
  // 일이라 여기까지 잠가야 FC-17이 막힌다(계획서 B4 가정 7)
  const stageDisabled = (id: Stage) => id === "structure"
    ? diagramGenerating || uploading || leaving || dialogOpen
    : locked;
  const stageTitle = (id: Stage) => id === "structure"
    ? (diagramGenerating ? "AI 생성이 끝나면 이동할 수 있습니다" : uploading ? "자료 업로드가 끝나면 이동할 수 있습니다" : undefined)
    : lockedTitle;
  const screenKeyValue = `${stage}:${screenKey}`;

  return (
    <main className="project-view project-shell">
      {/* DOM 순서는 상단 머리, 단계 목록, 본문이다. 화면 배치는 grid 영역으로 한다 (계획 6절 키보드 순서) */}
      <header className="project-topbar">
        <div className="topbar-title">
          <button onClick={goBack} disabled={locked} title={lockedTitle}>목록으로</button>
          <h1>{deck.meta.title}</h1>
        </div>
        <div className="topbar-status">
          {saveStatus && (
            <span className="header-save-status" tabIndex={-1} ref={saveStatusRef}>
              <StatusIndicator kind={saveStatus.kind} detail={saveStatus.detail} />
            </span>
          )}
          <SaveAnnouncer kind={saveStatus?.kind ?? "saved"} />
          {draftCount > 0 && (
            <button className="btn-text" onClick={openRecovery} disabled={locked}>보존한 변경 {draftCount}건</button>
          )}
          {activeJob && (
            // 서비스 전체에서 하나만 도는 AI 작업의 안내와 취소. 이 프로젝트의 작업도 보인다 (D2b-5a 리뷰 R14, R21)
            <p className="topbar-job">
              <StatusIndicator kind={activeJob.cancel_requested ? "cancel_requested" : "running"} />{" "}
              {activeJob.project === project.name
                ? "이 프로젝트에서 AI 생성이 진행 중입니다."
                : `다른 프로젝트(${activeJob.project})에서 AI 생성이 진행 중입니다. 끝난 뒤 생성할 수 있습니다.`}{" "}
              <button onClick={() => void api.cancelJob(activeJob.project, activeJob.id).then(refreshActiveJob)
                .catch((e) => setError(messageOf(e)))} disabled={activeJob.cancel_requested}>그 작업 취소</button>
            </p>
          )}
          {!ledgerAvailable && (
            // 원장을 열 수 없으면 AI 생성만 막힌다 (계획서 D2b-5c)
            <p className="topbar-job">작업 기록을 열 수 없어 AI 생성을 쓸 수 없습니다. 편집과 내보내기는 계속할 수 있습니다.</p>
          )}
        </div>
        <div className="topbar-actions">
          <AiStatusLine compact className="topbar-ai" />
          <AISettingsPanel disabled={locked} />
          <button onClick={openRecovery} disabled={locked} title={lockedTitle}>스냅샷 복구</button>
        </div>
      </header>
      <JobAnnouncer active={activeJob} />
      <aside className="stage-sidebar">
        <nav aria-label="보고서 작성 단계">
          <ol className="stage-list">
            {STAGES.map((s, index) => (
              <li key={s.id}>
                <button className="stage-button" aria-current={!showRecovery && stage === s.id ? "step" : undefined}
                  disabled={stageDisabled(s.id)} title={stageTitle(s.id)} onClick={() => void switchStage(s.id)}>
                  <span className="stage-number" aria-hidden="true">{index + 1}</span>
                  <span className="stage-label">{s.label}</span>
                </button>
              </li>
            ))}
          </ol>
        </nav>
      </aside>
      <div className="stage-body">
        {error && (
          <p role="alert">{error} <button onClick={() => setError("")}>닫기</button></p>
        )}
        {conflict && (
          <p role="alert">
            {conflict === "batch_here"
              ? "생성한 장이 문서에 반영되었습니다. 이 화면의 저장하지 않은 변경은 필요하면 복사해 둔 뒤 서버 내용을 다시 읽어 주세요."
              : "다른 창이나 프로그램에서 먼저 저장되었습니다."}{" "}
            {/* 다른 이동 버튼과 같은 조건으로 잠근다: 업로드 진행 중 눌러 자료 화면이 통째로
                언마운트되면, 나중에 응답한 업로드 결과가 화면에 영구히 반영되지 않는다(B 묶음
                최종 리뷰 major F-1) */}
            <button onClick={reloadDeck} disabled={locked}
              title={aiBusy ? "AI 생성이 끝나면 다시 읽을 수 있습니다"
                : uploading ? "자료 업로드가 끝나면 다시 읽을 수 있습니다" : undefined}>서버 내용 다시 읽기</button>
          </p>
        )}
        {dialogOpen && (
          <AiConsentDialog statusSnapshot={consentStatus} onConfirm={() => closeConsentDialog(true)} onCancel={() => closeConsentDialog(false)} />
        )}
        {showRecovery && (
          <RecoveryScreen project={project} deck={deck} onConflict={onConflict}
            onOpen={(next, chapterId) => closeRecovery(next, chapterId)}
            onBack={() => closeRecovery()} />
        )}
        {!showRecovery && stage === "purpose" && (
          <ReportPurposeScreen key={screenKeyValue} project={project} deck={deck} onDeckChange={setDeck}
            onScreenReady={(f) => { flushScreen.current = f; }} onDirtyChange={setDirty} onConflict={onConflict}
            onSaveStatusChange={setSaveStatus} />
        )}
        {!showRecovery && stage === "sources" && (
          <SourcesScreen key={screenKeyValue} project={project}
            onScreenReady={(f) => { flushScreen.current = f; }}
            onDirtyChange={setDirty} onBusyChange={setUploading} onSaveStatusChange={setSaveStatus} />
        )}
        {!showRecovery && stage === "structure" && (
          <StructureScreen key={screenKeyValue} project={project} deck={deck} onDeckChange={setDeck}
            onDone={() => setStage("editor")} onBusyChange={setGenerating} onConflict={onConflict}
            onScreenReady={f => { flushScreen.current = f; }} onDirtyChange={setDirty}
            onSaveStatusChange={setSaveStatus} onJobRegistered={onJobRegistered} focusChapterId={focusChapter} />
        )}
        {!showRecovery && stage === "editor" && (
          <EditorScreen key={screenKeyValue} project={project} deck={deck} onDeckChange={setDeck}
            onEditorReady={(f) => { flushScreen.current = f; }}
            onConflictHint={() => { justConflicted.current = true; }}
            onDirtyChange={setDirty} onBusyChange={setDiagramGenerating}
            onSaveStatusChange={setSaveStatus} onFocusSaveStatus={focusSaveStatus} onDraftsChanged={onDraftsChanged}
            initialChapterId={focusChapter} />
        )}
        {!showRecovery && stage === "review" && (
          <ReviewScreen key={screenKeyValue} projectName={project.name} hasSlides={hasSlides} exporting={exporting}
            exportDisabled={locked} exportTitle={lockedTitle}
            exportResult={exportResult?.projectName === project.name ? exportResult.result : null}
            historyRevision={historyRevision} onExport={() => void doExport()}
            onScreenReady={guard => { flushScreen.current = guard; }}
            onDirtyChange={onReviewDirty} />
        )}
      </div>
    </main>
  );
}
