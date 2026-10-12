import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { setConsentPrompter } from "../api/aiGate";
import { api, messageOf, notifyProject, onProjectEvent, onRemoteProjectEvent, savedEtag, TERMINAL_JOB_STATES, type ActiveJob, type AppStatus, type Deck, type ExportResult, type ProjectInfo, type ProjectProgress } from "../api/client";
import { ActiveJobContext, type ActiveJobState } from "../ui/ActiveJobNotice";
import { AISettingsPanel } from "./AISettingsPanel";
import { AiConsentDialog } from "./AiConsentDialog";
import { EditorScreen } from "./EditorScreen";
import { ExportHistoryPanel } from "./ExportHistoryPanel";
import { RecoveryScreen } from "./RecoveryScreen";
import { ReportPurposeScreen, type PurposePreserveResult } from "./ReportPurposeScreen";
import { formatSavedAt } from "../api/time";
import { STEP_LABELS } from "./GenerationSteps";
import { ReviewScreen } from "./ReviewScreen";
import { AiStatusLine } from "../ui/AiStatusLine";
import { JobAnnouncer, SaveAnnouncer, StatusIndicator, type SaveStatus } from "../ui/StatusIndicator";
import { SourcesScreen } from "./SourcesScreen";
import { EMPTY_BRIEF, StructureScreen, type StructureBrief } from "./StructureScreen";
import { batchSummary, JOB_STAGE, stageLimitations, stageProgress, stageStatus, type Stage } from "./stageStatus";

// 다섯 단계 (개정판 D3a-2, 계획 4.1, 제품 설계 3절). 단계 화면은 전환 때 언마운트한다: 숨긴 채 마운트를
// 유지하면 화면이 옛 사본을 든 채 전역 저장 ETag만 새로 바뀌는 이음매(계획 사실 14, 15)가 다시 생긴다
export type { Stage } from "./stageStatus";
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

export function ProjectView({ project, onBack, jobPollMs = 1000, purposeSaveMs }: {
  project: ProjectInfo; onBack: () => void; jobPollMs?: number;
  purposeSaveMs?: number;  // 보고 목적 자동 저장 지연. 시험이 줄인다 (D3b-5)
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
  // 구성 단계의 주안점과 목표 장수. 저장하지 않는 값이라 이 화면이 들고 있어 단계 이동과 다시 마운트 사이에 남는다
  // (계획 4.4, 사실 13). D3a-5의 항목을 D3a-2 리뷰 R6 반영으로 당겼다
  const [structureBrief, setStructureBrief] = useState<StructureBrief>(EMPTY_BRIEF);
  const editorChapter = useRef<string | null>(null);  // 편집 화면에서 고른 장. 다시 마운트해도 같은 장을 고른다 (R6)
  const onEditorChapterChange = useCallback((id: string | null) => { editorChapter.current = id; }, []);
  // 사용자가 단계를 옮겼으면 새 현재 단계 버튼으로 초점을 돌려준다. 이동 중에는 단계 버튼이 잠겨 초점이
  // 문서 본문으로 빠지기 때문이다 (D3a-2 리뷰 R12)
  const focusStageAfterMove = useRef(false);
  const [generating, setGenerating] = useState(false);  // 구조안 승인 후 장별 순차 생성 진행 중 (쓰기 포크 차단)
  // 편집 화면을 떠날 수 없는 동안(도식 작성 창이 열려 있음, 템플릿 전환 전 저장) 참이다 (D3a-5 리뷰 R10)
  const [diagramGenerating, setDiagramGenerating] = useState(false);
  const [leaving, setLeaving] = useState(false);        // 화면 이탈 전 플러시 진행 중: 모든 이탈 경로 버튼을 잠근다
  const [dirty, setDirty] = useState(false);            // 현재 화면에 저장하지 않은 변경이 있다 (beforeunload 경고용)
  // 자료 단계의 XLSX 업로드가 진행 중이다(계획서 B4 가정 7). generating과 합치지 않는다: 구성 단계는
  // 생성 중에는 잠그지 않는 예외가 있는데, 업로드는 자료 단계 안의 일이라 구성 단계까지 잠가야 FC-17이 막힌다
  const [uploading, setUploading] = useState(false);
  const [conflict, setConflict] = useState<Conflict>(null);  // 다른 창이나 프로그램, 또는 묶음이 먼저 저장했다
  // 늘리면 편집 화면과 보고 목적 화면이 충돌 처리로 들어간다 (B2, D3b-5: 보고 목적은 자동 저장을 멈춘다)
  const [conflictSignal, setConflictSignal] = useState(0);
  // 보고 목적 화면의 충돌 보존. 실패한 뒤 다시 누르면 복사 상자를 본 것으로 보고 버리기 확인으로 넘어간다 (B9)
  const preserveScreen = useRef<null | (() => Promise<PurposePreserveResult>)>(null);
  const preserveFailed = useRef(false);
  const [preservedNotice, setPreservedNotice] = useState("");
  // 이 화면을 연 시각. 다시 연 단계 화면은 이 시각 뒤에 끝난 작업의 실패만 보인다(새로고침마다 오래된 실패를
  // 되풀이하지 않는다, D3a-β 재리뷰 F2)
  const [openedAt] = useState(() => Date.now());
  // 사용자가 처음 확인이 끝나기 전에 단계를 옮겼는가. 그랬으면 열 때의 묶음으로 단계를 바꾸지 않는다 (재리뷰 F7)
  const userMoved = useRef(false);
  // 편집 화면의 도식 AI 호출 중(작성 창을 닫은 뒤 포함). 구성 화면의 바쁨과 나눠 든다: 닫힌 작성 창의 늦은
  // 해제가 구성 화면의 바쁨을 내리지 않게 한다 (재리뷰 F10)
  const [editorAiBusy, setEditorAiBusy] = useState(false);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>(null);  // 상단 머리의 저장 상태 (계획 4.1 출처 표)
  const [draftCount, setDraftCount] = useState(0);  // 충돌로 보존한 변경 건수 (C18)
  const [draftsRevision, setDraftsRevision] = useState(0);
  const saveStatusRef = useRef<HTMLSpanElement | null>(null);
  // 단계 상태 (D3a-3, 계획 4.2). undefined는 첫 조회 전이다. 조회가 실패하면 "확인하지 못함"으로 보이고 준비됨으로 두지 않는다
  const [progress, setProgress] = useState<ProjectProgress | undefined>(undefined);
  const [progressFailed, setProgressFailed] = useState(false);
  const progressSeq = useRef(0);
  // AI 전송 고지 대화 상자 (계획서 B3): 열려 있는 동안 사용자의 선택을 담을 resolve 함수를 들고 있는다.
  // null이 아니면 대화 상자가 열려 있다는 뜻이라 다른 상태와 함께 잠금 조건에도 쓴다
  const [consentResolve, setConsentResolve] = useState<((granted: boolean) => void) | null>(null);
  const [consentStatus, setConsentStatus] = useState<AppStatus | undefined>(undefined);
  // "declined"는 화면이 떠나기 전 확인에서 사용자가 머물기를 골랐다는 뜻이다. 실패 안내를 띄우지 않는다 (D3a-5)
  const flushScreen = useRef<null | (() => Promise<boolean | "declined">)>(null);
  // leaveScreen이 flush 실패의 일반 배너를 띄우기 전에 확인한다: onConflict가 이미 그 실패를
  // 설명했으면(플러시 도중 412) 중복 배너를 생략한다 (A5b 리뷰 발견 3)
  const justConflicted = useRef(false);
  // 서비스 전체의 진행 중 AI 작업 (D2b-5a, 계획서 5.9). 확인 전에는 생성 중과 같이 잠근다(새로고침 직후 잠금 공백 방지)
  const [jobChecked, setJobChecked] = useState(false);
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  const [ledgerAvailable, setLedgerAvailable] = useState(true);
  const [activeRevision, setActiveRevision] = useState(0);  // 진행 작업 조회가 끝난 횟수 (실패 안내가 작업 종결을 판정한다)
  const checkSeq = useRef(0);
  const checkedOnce = useRef(false);
  // 처음 연 순간의 묶음 여부. 첫 조회의 답으로만 정한다: 첫 답이 오기 전에 다른 탭의 알림으로 한 조회가 먼저
  // 끝나면 열고 난 뒤 시작된 묶음을 "열 때 이미 돌던 묶음"으로 잘못 보았다 (D3a-β 리뷰 B8)
  const openedWithBatch = useRef<boolean | null>(null);
  const refreshActiveJob = useCallback(async () => {
    const seq = ++checkSeq.current;
    try {
      const status = await api.getActiveJob();
      if (seq === 1 && openedWithBatch.current === null) {
        const opened = status.active?.project === project.name && status.active.kind === "chapters";
        openedWithBatch.current = opened;
        if (opened && !userMoved.current) setStage("structure");
      }
      if (seq !== checkSeq.current) return;  // 늦게 온 옛 응답은 버린다 (D2b-5a 리뷰 R18)
      setActiveJob(status.active ?? null);
      setLedgerAvailable(status.ledger_available);
      setActiveRevision((n) => n + 1);
    } catch {
      if (seq === 1 && openedWithBatch.current === null) openedWithBatch.current = false;
      if (seq !== checkSeq.current) return;
      // 첫 확인이 실패하면 잠그지 않는다(생성 버튼이 원인을 안내한다). 진행 중으로 확인한 작업은 놓지 않고
      // 새 객체로 바꿔 다음 조회를 예약한다 (D2b-5a 리뷰 R4)
      setActiveJob((previous) => (previous ? { ...previous } : null));
    } finally {
      if (seq === checkSeq.current) { setJobChecked(true); checkedOnce.current = true; }
    }
  }, [project.name]);
  useEffect(() => {
    void refreshActiveJob();
    const onFocus = () => void refreshActiveJob();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refreshActiveJob]);
  // 진행 중 작업이 있는 동안만 다시 확인한다. 조회가 끝날 때마다(activeRevision) 다음 조회를 예약한다: 응답이 앞과
  // 같은 객체여도 조회가 멈추지 않게 한다
  useEffect(() => {
    if (!activeJob) return;
    const timer = setTimeout(() => void refreshActiveJob(), jobPollMs);
    return () => clearTimeout(timer);
  }, [activeJob, activeRevision, jobPollMs, refreshActiveJob]);
  // 이 탭이 작업을 등록하거나 따라가던 작업이 끝나면 바로 다시 확인한다. 진행 작업 조회는 처음 열 때와 창 초점에만
  // 일어나 같은 탭이 등록한 작업을 몰랐다(계획 사실 11). 등록을 알고 나면 위 조회가 이어지므로, 그 작업을 조회하던
  // 화면이 내려가도 종결을 놓치지 않는다 (D3a-5, D3a-3 리뷰 R9)
  useEffect(() => onProjectEvent((event) => {
    if (event.kind === "job_started" || event.kind === "job_ended") void refreshActiveJob();
  }), [refreshActiveJob]);
  // 다른 탭의 알림 (D3a-6, 계획 4.5, β R15). 진행 작업이 없는 탭도 창 초점 없이 다른 탭의 작업 시작과 종결을 안다.
  // 받는 탭은 서버를 다시 조회만 한다(진행 작업은 서비스 전체 하나라 어느 프로젝트의 알림이든 조회한다)
  useEffect(() => onRemoteProjectEvent((event) => {
    if (event.kind === "job_started" || event.kind === "job_ended") void refreshActiveJob();
  }), [refreshActiveJob]);
  // 실패 안내와 화면 안 취소 버튼이 읽는 머리의 진행 작업. 그릴 때마다 새 객체를 만들면 그것을 듣는 부품의
  // 효과가 매번 다시 돌아 진행 작업 조회를 되풀이한다 (D3a-5)
  const activeJobState = useMemo<ActiveJobState>(() => ({ active: activeJob, revision: activeRevision,
    refresh: () => void refreshActiveJob() }), [activeJob, activeRevision, refreshActiveJob]);
  // 진행 작업에서 사라진 작업은 원장에서 결과를 읽어 종결을 알린다. 그 작업을 조회하던 화면이 내려갔으면 종결
  // 알림을 낼 곳이 없고, 진행 작업의 사라짐만으로는 결과를 몰라 "끝났습니다"와 결과 문구를 두 번 알렸다
  // (D3a-5, 묶음 리뷰 A12). 결과를 읽지 못하면 상태 없이 알린다(알림 쪽이 끝났다고만 말한다)
  const previousActive = useRef<ActiveJob | null>(null);
  useEffect(() => {
    const before = previousActive.current;
    previousActive.current = activeJob;
    if (!before || before.id === activeJob?.id) return;
    void Promise.resolve().then(() => api.getJob(before.project, before.id))
      .then((view) => (TERMINAL_JOB_STATES.has(view.state) ? view : null))
      .catch(() => null)
      .then((view) => notifyProject({ kind: "job_ended", project: before.project, jobId: before.id,
        state: view?.state, jobKind: view?.kind ?? before.kind }, { broadcast: false }));
  }, [activeJob]);
  // 잠금은 화면이 보고하는 바쁨이 아니라 서버의 진행 작업으로 정한다 (D3a-5, 계획 4.4 표). 이 프로젝트의 장 생성
  // 묶음 중에는 덱 편집을 읽기 전용으로, 내보내기와 복구와 다시 읽기와 검수 기록을 잠그고, 단계 이동은 막지
  // 않는다. 진행 작업을 확인하기 전에는 묶음일 수 있으므로 묶음과 같이 잠근다(새로고침 직후 잠금 공백 방지)
  const thisProjectJob = activeJob?.project === project.name ? activeJob : null;
  const batchHere = thisProjectJob?.kind === "chapters";
  const batchLocked = batchHere || !jobChecked;
  // 진행 API 다시 조회. 처음 열 때, 공통 알림(저장 성공, 작업 등록, 작업 종결) 뒤, 창 초점을 얻을 때다.
  // 1회 소요 시간은 이 Mac에서 작업 행 0건 2.4ms, 2,000건 69.4ms(중앙값)라 알림마다 조회한다. 늦은 응답은 버린다
  const refreshProgress = useCallback(async () => {
    const seq = ++progressSeq.current;
    try {
      const next = await api.getProgress(project.name);
      if (seq !== progressSeq.current) return;
      setProgress(next);
      setProgressFailed(false);
    } catch {
      if (seq === progressSeq.current) setProgressFailed(true);
    }
  }, [project.name]);
  useEffect(() => {
    if (project.status !== "ok") return;
    void refreshProgress();
    const off = onProjectEvent((event) => { if (event.project === project.name) void refreshProgress(); });
    const offRemote = onRemoteProjectEvent((event) => { if (event.project === project.name) void refreshProgress(); });
    const onFocus = () => void refreshProgress();
    window.addEventListener("focus", onFocus);
    return () => { off(); offRemote(); window.removeEventListener("focus", onFocus); };
  }, [project.name, project.status, refreshProgress]);
  // 진행 작업이 바뀌면(다른 탭의 작업이 시작되거나 끝남) 단계 상태도 다시 읽는다
  const activeJobId = activeJob?.id ?? null;
  const seenJobId = useRef<string | null>(null);
  useEffect(() => {
    if (seenJobId.current !== activeJobId && project.status === "ok") void refreshProgress();
    seenJobId.current = activeJobId;
  }, [activeJobId, project.status, refreshProgress]);
  // 이 프로젝트를 열 때 이미 묶음이 돌고 있으면 진행 표시가 있는 구성 단계를 연다(위 첫 조회). 그 뒤에 나타난
  // 묶음은 편집 단계의 저장을 거치지 않고 단계를 바꾸지 않도록 안내만 한다 (D2b-5a 리뷰 R3, R18)
  // 이 탭이 등록한 묶음의 작업 ID. 묶음 종결 뒤 충돌 안내를 사실에 맞게 쓴다 (계획 4.1)
  // 같은 탭의 모든 작업 등록 알림도 담는다: 창 닫기 경고와 실패 알림을 이 탭이 시작한 작업으로 가른다
  // (D3a-7 사용자 결정, β 리뷰 B9, 재리뷰 F8)
  const startedHere = useRef<Set<string>>(new Set());
  const onJobRegistered = useCallback((id: string) => { startedHere.current.add(id); }, []);
  // 이 탭의 화면이 따라가기 시작한 작업. 그 실패는 화면이 원인별로 보이므로 머리에 다시 알리지 않는다 (D3b-7 리뷰 R1)
  const followedHere = useRef<Set<string>>(new Set());
  const onJobFollowed = useCallback((id: string) => { followedHere.current.add(id); }, []);
  useEffect(() => onProjectEvent((event) => {
    if (event.kind === "job_started" && event.jobId) startedHere.current.add(event.jobId);
  }), []);
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
  const generatingRef = useRef(false);
  // 다른 단계에 있는 동안 이 프로젝트의 AI 생성이 실패하거나 끝나지 않으면 머리에 보이게 알린다. 종결 낭독은 보이지
  // 않으므로, 결과를 확인할 단계를 버튼으로 잇는다 (D3a-β 리뷰 B1)
  // 다시 연 화면이 지난 실패를 원인별로 보이는 작업 종류(구성 화면과 편집 단계의 생성 패널). 그 밖(도식, 재작성,
  // 수리)은 다시 연 화면에 실패가 남지 않으므로 알림을 그 단계에 가도 지우지 않는다 (재리뷰 F3)
  const REOPEN_SHOWS = new Set(["structure", "chapters", "chapter", "condense"]);
  const [jobProblem, setJobProblem] = useState<{ stage: Stage; state: string; kind: string; target: string | null;
    jobId: string | null } | null>(null);
  useEffect(() => onProjectEvent((event) => {
    if (event.project !== project.name) return;
    // 같은 프로젝트에서 새 작업이 시작되면 지난 실패 알림을 내린다 (재리뷰 F9)
    if (event.kind === "job_started") { setJobProblem(null); return; }
    if (event.kind !== "job_ended" || !event.state || !event.jobKind) return;
    if (!["failed", "interrupted", "remote_completion_unknown"].includes(event.state)) return;
    const target = JOB_STAGE[event.jobKind];
    // 그 단계를 보고 있고 이 탭이 시작한 작업이면 그 화면이 결과를 보인다. 다른 탭이 시작한 작업은 이 탭의 화면이
    // 따라가지 않을 수 있으므로 그 단계에 있어도 알린다 (재리뷰 F8, D3a-7 사용자 결정)
    // 이 탭의 화면이 따라가던 작업(다른 탭이 시작해 다시 연 화면이 이어서 조회한 작업)도 화면이 결과를 보인다 (D3b-7 리뷰 R1)
    const shownOnScreen = !showRecoveryRef.current && stageRef.current === target && !!event.jobId
      && (startedHere.current.has(event.jobId) || followedHere.current.has(event.jobId));
    if (!target || shownOnScreen) return;
    setJobProblem({ stage: target, state: event.state, kind: event.jobKind, target: event.target ?? null,
      jobId: event.jobId ?? null });
  }), [project.name]);
  useEffect(() => onRemoteProjectEvent((event) => {
    if (event.project === project.name && event.kind === "job_started") setJobProblem(null);
  }), [project.name]);
  // 그 단계로 옮겨 화면을 새로 열 때만 지운다. 이미 그 단계에 있는 동안 다른 탭의 실패를 받았으면 화면이 다시 열리지
  // 않아 원인을 보이지 않으므로 알림을 남긴다 (D3a-7 사용자 결정, F8)
  const openedView = useRef({ stage, showRecovery });
  useEffect(() => {
    const moved = openedView.current.stage !== stage || openedView.current.showRecovery !== showRecovery;
    openedView.current = { stage, showRecovery };
    if (moved && !showRecovery && jobProblem?.stage === stage && REOPEN_SHOWS.has(jobProblem.kind)) setJobProblem(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage, showRecovery, jobProblem]);
  // 구성 화면이 다시 열려도 이미 보인 실패를 되풀이하지 않는다 (B1)
  const seenJobFailures = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (wasBatchHere.current && !batchHere) {
      const endedJob = lastBatchId.current;
      // 서버 저장본의 ETag를 이 탭의 저장 ETag와 비교한다(이 탭의 값은 바꾸지 않는다). 다르면 이 탭이 따라가지 못했다.
      // 확인이 실패하면 판정하지 않고 다음 저장의 충돌 검사에 맡긴다 (β 리뷰 R1, D3a-7: 412 콘솔 오류를 내지 않는다)
      api.peekDeckEtag(project.name)
        .then((etag) => etag !== null && etag !== savedEtag(project.name))
        .catch(() => false)
        .then((changed) => {
          if (!changed) return;
          // 구성 화면이 생성 작업을 따라가는 중이면(같은 탭의 묶음) 그 화면이 종결 때 덱을 다시 읽고 편집 단계로
          // 옮긴다. 여기서 다시 마운트하면 그 조회가 끊겨 편집 단계 이동과 결과 안내가 사라진다 (D3a-2 리뷰 R1)
          if (!showRecoveryRef.current && stageRef.current === "structure" && generatingRef.current) return;
          // 복구 화면은 덱 사본을 들지 않고 미저장 신호도 올리지 않는다. 그 가정이 깨져도 충돌 안내 대신 덱만
          // 다시 읽도록 복구 화면을 사본 단계에서 뺀다
          const holdsCopy = !showRecoveryRef.current && DECK_COPY_STAGES.has(stageRef.current);
          if (holdsCopy && dirtyRef.current) {
            // 편집 단계는 자기 충돌 처리(보존 뒤 서버 내용으로 되돌리기)로 보낸다. 여기서 다시 읽기 안내를 겹쳐 띄우면
            // 보존하지 않는 버튼이 하나 더 생겼다 (D3a-β 리뷰 B2)
            if (stageRef.current === "editor") { setConflictSignal((n) => n + 1); return; }
            // 보고 목적은 자동 저장을 멈춰야 다음 저장의 412가 원인 문구를 "다른 창이나 프로그램"으로 바꾸지 않는다 (리뷰 U3)
            if (stageRef.current === "purpose") setConflictSignal((n) => n + 1);
            setConflict(endedJob !== null && startedHere.current.has(endedJob) ? "batch_here" : "other");
            return;
          }
          api.getDeck(project.name).then((fresh) => {
            setDeck(fresh);
            if (holdsCopy) {
              if (stageRef.current === "editor") setFocusChapter(editorChapter.current);  // 고른 장을 유지한다
              setScreenKey((k) => k + 1);  // 사본까지 새 덱으로 만든다
            }
          }).catch(() => {});
        });
    }
    wasBatchHere.current = batchHere;
    if (batchHere && activeJob) lastBatchId.current = activeJob.id;
  }, [batchHere, activeJob, project.name]);
  generatingRef.current = generating;
  // 화면 바쁨(generating, diagramGenerating)은 그 화면 안의 입력 잠금과, 등록 응답 전이라 서버가 아직 모르는
  // 이 탭의 작업에만 쓴다. 화면이 바뀌면 내려간 화면의 바쁨은 버린다: 언마운트로 조회를 멈춘 화면은 바쁨을 내리지
  // 않았다 (계획 사실 10)
  useEffect(() => { setGenerating(false); setDiagramGenerating(false); setEditorAiBusy(false); }, [stage, screenKey, showRecovery]);
  // 지금 단계에서 저장이 있었는가. "저장됨"은 저장한 뒤에만 보인다. 새 프로젝트의 빈 단계에 완료색 체크가 붙어
  // 단계 목록의 "시작 전"과 어긋나게 읽혔다 (D3a-7 사용자 결정, α 묶음 리뷰 A19)
  const [savedHere, setSavedHere] = useState(false);
  useEffect(() => { setSavedHere(false); }, [stage, screenKey, showRecovery]);
  // 보존 안내와 보존 실패 기록은 그 단계에서만 뜻이 있다 (D3b-5)
  useEffect(() => { setPreservedNotice(""); preserveFailed.current = false; }, [stage, showRecovery]);
  useEffect(() => onProjectEvent((event) => {
    if (event.kind === "saved" && event.project === project.name) setSavedHere(true);
  }), [project.name]);
  // 창 닫기 경고는 이 탭이 시작한 작업에만 띄운다. 다른 탭의 작업은 이 탭을 닫아도 결과가 남는다(계획 4.5,
  // D3a-7 사용자 결정, β 리뷰 B9)
  const startedJobRunning = thisProjectJob !== null && startedHere.current.has(thisProjectJob.id);
  const aiRunningHere = startedJobRunning || generating || diagramGenerating || editorAiBusy;
  const batchTitle = !jobChecked ? "작업 상태를 확인하는 중입니다" : "내용 생성이 끝나면 쓸 수 있습니다";

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
  // 서버 내용으로 되돌린 직후에는 화면이 저장본과 같으므로 저장 뒤와 같이 "저장됨"을 보이고 그리로 초점을 옮긴다.
  // 숨겨 둔 상태 칸은 다음 그리기에서 나타나므로 초점은 그린 뒤에 준다 (D3a-7, R5)
  const focusSaveAfterRender = useRef(false);
  const focusSaveStatus = useCallback(() => { setSavedHere(true); focusSaveAfterRender.current = true; }, []);
  useEffect(() => {
    if (focusSaveAfterRender.current && saveStatusRef.current) {
      focusSaveAfterRender.current = false;
      saveStatusRef.current.focus();
    }
  });
  useEffect(() => {
    if (!focusStageAfterMove.current || deck === null) return;
    const current = document.querySelector<HTMLButtonElement>(".stage-list [aria-current='step']");
    if (current) { focusStageAfterMove.current = false; current.focus(); }
  });
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
      // 이 프로젝트의 진행 작업을 서버 기준으로 본다. 화면을 옮겨도 작업이 도는 동안 경고하고, 끝나면 푼다 (D3a-5)
      const aiRunning = !window.slidecaptain && aiRunningHere;
      if (dirty || uploading || aiRunning) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty, uploading, aiRunningHere]);

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
      const result = await flushScreen.current();
      const flushed = result === true;
      if (flushed) {
        setDirty(false);
      } else if (result !== "declined" && !justConflicted.current && stage !== "review") {
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
    setError("");
    setDeck(null);
    api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
    setFocusChapter(chapterId ?? null);
    if (next) setStage(next);
  };

  // chapterId: 그 단계에서 미리 고를 장 (머리의 실패 알림이 편집 단계 작업의 장으로 보낸다, 재리뷰 F3)
  const switchStage = async (next: Stage, chapterId?: string | null) => {
    userMoved.current = true;
    // 복구 화면은 단계가 아니다. 단계를 고르면 복구 화면을 닫고 그 단계로 간다 (계획 4.1).
    // 복구 화면에는 이탈 확인이 없다(복원과 지우기는 각각 확인 창을 거친다)
    if (showRecovery) { focusStageAfterMove.current = true; closeRecovery(next); return; }
    if (next === stage) return;  // 지금 단계를 다시 고르면 아무것도 하지 않는다(화면이 다시 마운트되지 않아 저장 상태를 다시 올리지 않는다)
    if (await leaveScreen("이동을")) {
      setError("");
      setSaveStatus(null);
      setFocusChapter(chapterId ?? null);
      focusStageAfterMove.current = true;
      setStage(next);
    }
  };
  // 지금 단계의 화면을 다시 연다(결과 다시 보기). 화면이 다시 열리며 지난 실패를 원인별로 보인다 (B8)
  const reopenStage = async () => {
    if (!(await leaveScreen("다시 열기를"))) return;
    setError("");
    setSaveStatus(null);
    // 편집 단계는 실패한 장(없으면 고르던 장)을 다시 고르고, 다시 연 뒤 초점은 지금 단계 버튼으로 옮긴다 (리뷰 R7, R9)
    if (stage === "editor") setFocusChapter(jobProblem?.target ?? editorChapter.current);
    setJobProblem(null);
    focusStageAfterMove.current = true;
    setScreenKey((k) => k + 1);
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
    // 보고 목적의 미저장 입력은 보존본으로 남긴다 (D3b-5, B9). 보존에 실패하면 화면이 복사 상자를 보이고, 다시 누르면
    // 버리기 확인으로 넘어간다. 구성 화면의 폼 입력은 덱이 아니어서 보존하지 않고 버리기 전에 확인한다 (D2a-2)
    let kept = false;
    if (dirty && stage === "purpose" && preserveScreen.current && !preserveFailed.current) {
      const result = await preserveScreen.current();
      if (result.kind === "failed") { preserveFailed.current = true; return; }
      if (result.kind === "preserved") {
        kept = true;
        onDraftsChanged();
        setPreservedNotice(`저장하지 못한 보고 정보를 보존했습니다(${formatSavedAt(result.savedAt)}). 스냅샷 복구 화면의 "충돌로 보존한 변경"에서 보거나 복원할 수 있습니다.`);
      }
    }
    if (dirty && !kept && !window.confirm("저장하지 않은 입력이 사라집니다. 필요한 내용은 먼저 복사해 두세요. 서버 내용을 다시 읽을까요?")) return;
    preserveFailed.current = false;
    setConflict(null);
    setDirty(false);  // 서버 내용으로 자식 화면을 다시 마운트하므로 미저장 변경이 없다
    setDeck(null);
    // 화면 열쇠도 바꿔 반드시 다시 마운트한다. 보존을 기다린 뒤에는 클릭 처리 밖이라 덱 비우기와 새 덱 넣기가 한 번의
    // 렌더로 묶일 수 있고, 그러면 화면이 옛 입력을 든 채 남는다 (D3b-5)
    setScreenKey((k) => k + 1);
    api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
  };

  // 이동 잠금: 업로드(자료 단계 안의 일이라 FC-17), 이탈 전 플러시, 고지 대화 상자. 편집 화면의 도식 작성 창이 열려
  // 있거나 템플릿 전환 전 저장 중에도 잠근다. 편집 화면의 플러시가 그동안 이탈을 거절하기 때문이다(작성 창의 입력은
  // 덱이 아니다). 작성 창을 닫은 뒤 남은 AI 호출은 후보형 작업이라 잠그지 않는다 (계획 4.4, D3a-5 리뷰 R10)
  const navLocked = uploading || leaving || dialogOpen || diagramGenerating;
  const navTitle = uploading ? "자료 업로드가 끝나면 이동할 수 있습니다"
    : diagramGenerating ? "도식 작성 창을 닫거나 템플릿 전환이 끝나면 이동할 수 있습니다" : undefined;
  // 묶음 중 잠그는 머리 행동(스냅샷 복구, 보존한 변경, 서버 내용 다시 읽기). AI 설정은 어느 작업이든 잠근다:
  // 서버가 생성 중 설정 변경을 409로 거절한다 (계획 4.4)
  const recoveryLocked = navLocked || batchLocked;
  const recoveryTitle = navTitle ?? (batchLocked ? batchTitle : undefined);
  const aiSettingsLocked = uploading || leaving || dialogOpen || activeJob !== null || generating || editorAiBusy || !jobChecked;
  const stageDisabled = (_id: Stage) => navLocked;
  const stageTitle = (_id: Stage) => navTitle;
  const screenKeyValue = `${stage}:${screenKey}`;
  const shownSave = saveStatus && (saveStatus.kind !== "saved" || savedHere) ? saveStatus : null;

  return (
    <ActiveJobContext.Provider value={activeJobState}>
    <main className="project-view project-shell">
      {/* DOM 순서는 상단 머리, 단계 목록, 본문이다. 화면 배치는 grid 영역으로 한다 (계획 6절 키보드 순서) */}
      <header className="project-topbar">
        <div className="topbar-title">
          <button onClick={goBack} disabled={navLocked} title={navTitle}>목록으로</button>
          {/* 좁으면 말줄임으로 줄어들므로 전체 제목을 title로 둔다 (D3a-7) */}
          <h1 title={deck.meta.title}>{deck.meta.title}</h1>
        </div>
        <div className="topbar-status">
          {shownSave && (
            <span className="header-save-status" tabIndex={-1} ref={saveStatusRef}>
              <StatusIndicator kind={shownSave.kind} detail={shownSave.detail} />
            </span>
          )}
          <SaveAnnouncer kind={shownSave?.kind ?? null} />
          {draftCount > 0 && (
            <button className="btn-text" onClick={openRecovery} disabled={recoveryLocked} title={recoveryTitle}>보존한 변경 {draftCount}건</button>
          )}
        </div>
        <div className="topbar-actions">
          <AiStatusLine compact className="topbar-ai" />
          <AISettingsPanel disabled={aiSettingsLocked} />
          <button onClick={openRecovery} disabled={recoveryLocked} title={recoveryTitle}>스냅샷 복구</button>
        </div>
        {/* 진행 안내와 실패 알림은 문장이라 머리의 한 줄(제목, 저장 상태, 행동) 아래에 따로 둔다. 알림이 없으면 그리지 않아
            머리 높이가 저장 상태의 유무로 바뀌지 않는다 (D3a-7 사용자 결정, 리뷰 R9) */}
        {(activeJob || jobProblem || !ledgerAvailable) && (
          <div className="topbar-notices">
            {activeJob && (
              // 서비스 전체에서 하나만 도는 AI 작업의 안내와 취소. 이 프로젝트의 작업도 보인다 (D2b-5a 리뷰 R14, R21)
              <p className="topbar-job">
                <StatusIndicator kind={activeJob.cancel_requested ? "cancel_requested" : "running"} />{" "}
                {activeJob.project === project.name
                  // 구조안이면 실행 단계 이름을 덧붙인다. 시간은 쓰지 않는다 (계획 4.7, D3b-7 리뷰 R14, R16)
                  ? `이 프로젝트에서 AI 생성이 진행 중입니다${activeJob.step ? `(${STEP_LABELS[activeJob.step]})` : ""}.`
                  : `다른 프로젝트(${activeJob.project})에서 AI 생성이 진행 중입니다. 끝난 뒤 생성할 수 있습니다.`}{" "}
                <button onClick={() => void api.cancelJob(activeJob.project, activeJob.id).then(refreshActiveJob)
                  .catch((e) => setError(messageOf(e)))} disabled={activeJob.cancel_requested}>그 작업 취소</button>
              </p>
            )}
            {jobProblem && (
              <p className="topbar-job">
                <StatusIndicator kind="failed" />{" "}
                {STAGES.find((s) => s.id === jobProblem.stage)?.label} 단계의 AI 생성이{" "}
                {jobProblem.state === "failed" ? "실패했습니다" : "끝나지 않았습니다"}.{" "}
                {jobProblem.stage === stage && !showRecovery ? (
                  // 그 단계에 있는 탭이 받은 다른 탭의 실패: 다시 연 화면에 원인이 남는 종류만 다시 연다. 단계 이탈과 같은
                  // 확인(초안 이탈 확인과 편집 플러시)을 거친다 (B8, 리뷰 U19)
                  // 이 화면이 이미 보인 실패는 다시 열어도 보이지 않으므로 버튼을 두지 않는다 (D3b-7 리뷰 R1)
                  REOPEN_SHOWS.has(jobProblem.kind) && !(jobProblem.jobId && seenJobFailures.current.has(jobProblem.jobId)) && (
                    <button onClick={() => void reopenStage()} disabled={navLocked} title={navTitle}>결과 다시 보기</button>)
                ) : (
                  <button onClick={() => void switchStage(jobProblem.stage, jobProblem.target)} disabled={navLocked}
                    title={navTitle}>
                    {STAGES.find((s) => s.id === jobProblem.stage)?.label} 단계로 이동</button>
                )}{" "}
                <button className="btn-text" onClick={() => setJobProblem(null)}>닫기</button>
              </p>
            )}
            {!ledgerAvailable && (
              // 원장을 열 수 없으면 AI 생성만 막힌다 (계획서 D2b-5c)
              <p className="topbar-job">작업 기록을 열 수 없어 AI 생성을 쓸 수 없습니다. 편집과 내보내기는 계속할 수 있습니다.</p>
            )}
          </div>
        )}
      </header>
      <JobAnnouncer />
      <aside className="stage-sidebar">
        <nav aria-label="보고서 작성 단계">
          <ol className="stage-list">
            {STAGES.map((s, index) => {
              // 단계 상태는 버튼 밖의 다른 요소다. 버튼 이름은 단계 이름으로 두고 상태는 aria-describedby로 잇는다 (계획 4.2)
              const current = !showRecovery && stage === s.id;
              const status = stageStatus(s.id, { progress, failed: progressFailed, current, dirty,
                activeJob, projectName: project.name });
              // 조회가 실패하면 지난 응답의 장 요약을 보이지 않는다 (D3a-3 리뷰 R14)
              const summary = s.id === "structure" && !progressFailed ? batchSummary(progress?.jobs) : null;
              const statusId = `stage-status-${s.id}`;
              // 잠긴 이유. aria-describedby가 있으면 title은 설명에 쓰이지 않으므로 화면 낭독기 전용 요소로 함께 잇는다
              // (D3a-3 리뷰 R7)
              const lockReason = stageDisabled(s.id) ? stageTitle(s.id) : undefined;
              const lockId = `stage-lock-${s.id}`;
              const describedBy = [status || summary ? statusId : null, lockReason ? lockId : null].filter(Boolean).join(" ");
              return (
                <li key={s.id}>
                  <button className="stage-button" aria-current={current ? "step" : undefined}
                    aria-describedby={describedBy || undefined}
                    disabled={stageDisabled(s.id)} title={stageTitle(s.id)} onClick={() => void switchStage(s.id)}>
                    <span className="stage-number" aria-hidden="true">{index + 1}</span>
                    <span className="stage-label">{s.label}</span>
                  </button>
                  {lockReason && <span id={lockId} className="visually-hidden">{lockReason}</span>}
                  {(status || summary) && (
                    <span className="stage-status" id={statusId}>
                      {status && <StatusIndicator kind={status.kind} detail={status.detail} />}
                      {summary && <span className="stage-summary">{summary}</span>}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      </aside>
      <div className="stage-body">
        {error && (
          <p role="alert">{error} <button onClick={() => setError("")}>닫기</button></p>
        )}
        {preservedNotice && <p role="status">{preservedNotice}</p>}
        {conflict && (
          <p role="alert">
            {conflict === "batch_here"
              ? "생성한 장이 문서에 반영되었습니다. 이 화면의 저장하지 않은 변경은 필요하면 복사해 둔 뒤 서버 내용을 다시 읽어 주세요."
              : "다른 창이나 프로그램에서 먼저 저장되었습니다."}{" "}
            {/* 다른 이동 버튼과 같은 조건으로 잠근다: 업로드 진행 중 눌러 자료 화면이 통째로
                언마운트되면, 나중에 응답한 업로드 결과가 화면에 영구히 반영되지 않는다(B 묶음
                최종 리뷰 major F-1) */}
            <button onClick={reloadDeck} disabled={recoveryLocked}
              title={batchLocked ? "내용 생성이 끝나면 다시 읽을 수 있습니다"
                : uploading ? "자료 업로드가 끝나면 다시 읽을 수 있습니다" : undefined}>서버 내용 다시 읽기</button>
          </p>
        )}
        {dialogOpen && (
          <AiConsentDialog statusSnapshot={consentStatus} onConfirm={() => closeConsentDialog(true)} onCancel={() => closeConsentDialog(false)} />
        )}
        {showRecovery && (
          <RecoveryScreen project={project} deck={deck} onConflict={onConflict}
            restoreLockedReason={batchLocked ? (jobChecked ? "내용 생성이 끝나면 복원할 수 있습니다." : batchTitle) : undefined}
            onOpen={(next, chapterId) => closeRecovery(next, chapterId)}
            onBack={() => closeRecovery()} />
        )}
        {!showRecovery && stage === "purpose" && (
          <ReportPurposeScreen key={screenKeyValue} project={project} deck={deck} onDeckChange={setDeck}
            readOnly={batchLocked} readOnlyNotice={batchHere} conflictSignal={conflictSignal}
            onScreenReady={(f) => { flushScreen.current = f; }} onDirtyChange={setDirty} onConflict={onConflict}
            onPreserveReady={(f) => { preserveScreen.current = f; }} saveDelayMs={purposeSaveMs}
            onSaveStatusChange={setSaveStatus} onNext={() => void switchStage("sources")}
            nextDisabled={navLocked} nextTitle={navTitle}
            limitations={progressFailed ? [] : stageLimitations(progress, "purpose")} />
        )}
        {!showRecovery && stage === "sources" && (
          <SourcesScreen key={screenKeyValue} project={project} limitations={progressFailed ? [] : stageLimitations(progress, "sources")}
            batchRunning={batchHere} jobChecking={!jobChecked}
            onScreenReady={(f) => { flushScreen.current = f; }}
            onDirtyChange={setDirty} onBusyChange={setUploading} onSaveStatusChange={setSaveStatus} />
        )}
        {!showRecovery && stage === "structure" && (
          <StructureScreen key={screenKeyValue} project={project} deck={deck} onDeckChange={setDeck}
            onDone={() => { setError(""); setSaveStatus(null); setFocusChapter(null); setStage("editor"); }}
            onBusyChange={setGenerating} onConflict={onConflict} brief={structureBrief} onBriefChange={setStructureBrief}
            onScreenReady={f => { flushScreen.current = f; }} onDirtyChange={setDirty}
            onSaveStatusChange={setSaveStatus} onJobRegistered={onJobRegistered} onJobFollowed={onJobFollowed}
            focusChapterId={focusChapter}
            registeredJobs={startedHere.current} seenJobFailures={seenJobFailures.current} failuresSince={openedAt}
            limitations={progressFailed ? [] : stageLimitations(progress, "structure")} readOnly={batchLocked}
            readOnlyNotice={batchHere} onEditPurpose={() => void switchStage("purpose")} editPurposeDisabled={navLocked} />
        )}
        {!showRecovery && stage === "editor" && (
          <EditorScreen key={screenKeyValue} project={project} deck={deck} onDeckChange={setDeck}
            onEditorReady={(f) => { flushScreen.current = f; }}
            onConflictHint={() => { justConflicted.current = true; }}
            onDirtyChange={setDirty} onBusyChange={setDiagramGenerating} onAiBusyChange={setEditorAiBusy}
            onSaveStatusChange={setSaveStatus} onFocusSaveStatus={focusSaveStatus} onDraftsChanged={onDraftsChanged}
            initialChapterId={focusChapter} onChapterChange={onEditorChapterChange}
            readOnly={batchLocked} readOnlyNotice={batchHere} conflictSignal={conflictSignal}
            seenJobFailures={seenJobFailures.current} failuresSince={openedAt} />
        )}
        {!showRecovery && stage === "review" && (
          <ReviewScreen key={screenKeyValue} projectName={project.name} hasSlides={hasSlides} exporting={exporting}
            review={stageProgress(progress, "review")} progressFailed={progressFailed}
            exportDisabled={navLocked || batchLocked} exportTitle={navTitle ?? (batchLocked ? batchTitle : undefined)}
            recordsLocked={batchLocked} batchRunning={batchHere}
            exportResult={exportResult?.projectName === project.name ? exportResult.result : null}
            historyRevision={historyRevision} onExport={() => void doExport()}
            onScreenReady={guard => { flushScreen.current = guard; }}
            onDirtyChange={onReviewDirty} />
        )}
      </div>
    </main>
    </ActiveJobContext.Provider>
  );
}
