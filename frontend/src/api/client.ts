import { appFetch } from './transport';
import { ensureConsent } from "./aiGate";
import type { components } from "./types";

export type Deck = components["schemas"]["Deck"];
export type DeckMeta = components["schemas"]["DeckMeta"];
export type Chapter = components["schemas"]["Chapter"];
export type Structure = components["schemas"]["Structure"];
export type StoryPlan = components["schemas"]["StoryPlan"];
export type ReportBrief = components["schemas"]["ReportBrief"];
export type Slide = components["schemas"]["Slide"];
export type Slots = Slide["slots"];
export type Bullet = components["schemas"]["Bullet"];  // level이 필수 필드다 (기본값이 있어도 생성 타입에서는 필수)
export type Preset = components["schemas"]["Preset"];
export type ProjectInfo = components["schemas"]["ProjectInfo"];
export type SnapshotInfo = components["schemas"]["SnapshotInfo"];
export type DraftInfo = components["schemas"]["DraftInfo"];
export type ProjectProgress = components["schemas"]["ProjectProgress"];
export type DraftReason = DraftInfo["reason"];
export type DraftSource = DraftInfo["source"];
export type RenderPlan = components["schemas"]["RenderPlan"];
export type SlidePlan = components["schemas"]["SlidePlan"];
export type Frame = components["schemas"]["Frame"];
export type Para = components["schemas"]["Para"];
export type TablePlan = components["schemas"]["TablePlan"];
export type CapacityWarning = components["schemas"]["CapacityWarning"];
export type StructureResult = components["schemas"]["StructureResult"];
export type StoryRewriteResult = components["schemas"]["StoryRewriteResult"];
export type StoryRepairResult = components["schemas"]["StoryRepairResult"];
export type StoryRepairRequest = components["schemas"]["StoryRepairRequest"];
export type DocumentChangeBasis = components["schemas"]["DocumentChangeBasis"];
export type DocumentChangePreview = components["schemas"]["DocumentChangePreview"];
export type DocumentChangeRequest = components["schemas"]["DocumentChangeRequest"];
export type DocumentChangeApplyRequest = components["schemas"]["DocumentChangeApplyRequest"];
export type EvidenceSelection = components["schemas"]["EvidenceSelection"];
export type EvidenceMigrationRequest = components["schemas"]["EvidenceMigrationRequest"];
export type EvidenceMigrationApplyRequest = components["schemas"]["EvidenceMigrationApplyRequest"];
export type ChapterResult = components["schemas"]["ChapterResult"];
export type JobView = components["schemas"]["JobView"];
export type ChapterView = components["schemas"]["ChapterView"];
export type ActiveJob = components["schemas"]["ActiveJob"];
export type ActiveJobStatus = components["schemas"]["ActiveJobStatus"];
export type NumericReviewReport = components["schemas"]["NumericReviewReport"];
export type SemanticSuspectReport = components["schemas"]["SemanticSuspectReport"];
export type QualityReport = components["schemas"]["QualityReport"];
export type ExportResult = components["schemas"]["ExportResult"];
export type ExportHistoryItem = components["schemas"]["ExportHistoryItem"];
export type ExportHistoryPage = components["schemas"]["ExportHistoryPage"];
export type ExportHistoryDetail = components["schemas"]["ExportHistoryDetail"];
export type ExportReviewRequest = components["schemas"]["ExportReviewRequest"];
export type ExportReviewRecord = components["schemas"]["ExportReviewRecord"];
export type ExportReviewCategoryState = components["schemas"]["ExportReviewCategoryState"];
export type ExportReviews = components["schemas"]["ExportReviews"];
export type ExportQualification = components["schemas"]["ExportQualification"];
export type QualificationRequest = components["schemas"]["QualificationRequest"];
export type IndependentReviewRequest = components["schemas"]["IndependentReviewRequest"];
export type FinalPublication = components["schemas"]["FinalPublication"];
export type GenerationUsage = components["schemas"]["GenerationUsage"];
export type TemplateName = Chapter["template"];
export type UploadResult = components["schemas"]["UploadResult"];
export type AppStatus = components["schemas"]["AppStatus"];
export type LoginStatus = components["schemas"]["LoginStatus"];
export type AISettings = components["schemas"]["AISettings"];
export type AISelection = Required<components["schemas"]["AISelection"]>;
export type ReconcileDiagramRequest = components["schemas"]["ReconcileDiagramRequest"];
export type DiagramGenerationResult = components["schemas"]["DiagramGenerationResult"];
export type GenerateDiagramRequest = Omit<components["schemas"]["GenerateDiagramRequest"],"mode"> & Partial<Pick<components["schemas"]["GenerateDiagramRequest"],"mode">>;
export type ProviderId = AISelection["provider"];
export type LoginAttempt = components["schemas"]["LoginAttempt"];

export class ApiError extends Error {
  // active: 409 generation_active 응답이 담은 진행 중 작업 (D2b-5b). 화면이 그 작업의 취소 버튼을 보인다.
  // job: 작업이 실패로 끝나 던진 오류의 작업 (D3a-4). 실패 안내가 원인 분류와 작업 ID, 시각을 읽는다
  constructor(public status: number, detail: string, public code?: string, public active?: ActiveJob, public job?: JobView | null) {
    super(detail);
  }
}

export function isStaleStoryPlan(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.code === "stale_story_plan";
}

// AI 전송 고지 관문(계획서 B3)에서 사용자가 취소했을 때 던진다. status 0은 서버 응답이 아니라
// 요청 자체가 나가지 않았음을 나타낸다. 화면은 이 오류를 role="alert" 배너가 아닌 안내 문구로 보인다.
export class AiConsentDeclined extends ApiError {
  constructor() {
    super(0, "AI 전송을 취소했습니다.");
  }
}

export function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : "서버에 연결하지 못했습니다. 앱을 다시 시작해 주세요.";
}

async function throwIfFailed(r: Response): Promise<void> {
  if (r.ok) return;
  let detail = "요청이 실패했습니다. 잠시 후 다시 시도해 주세요.";
  let code: string | undefined;
  let active: ActiveJob | undefined;
  try {
    const body = await r.json();
    if (typeof body.code === "string") code = body.code;
    if (body.active && typeof body.active === "object" && typeof body.active.id === "string") active = body.active;
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) {
      // FastAPI 입력 오류에는 원래 입력도 담긴다. 메시지만 취하고 입력/ctx를 출력하지 않는다.
      const messages = body.detail.flatMap((item: unknown) => {
        if (item && typeof item === "object" && "msg" in item && typeof item.msg === "string") {
          return [item.msg.replace(/^Value error, /, "")];
        }
        return [];
      });
      if (messages.length) detail = [...new Set(messages)].join("\n");
    }
  } catch {
    // JSON 본문이 아니면 기본 문구 유지
  }
  throw new ApiError(r.status, detail, code, active);
}

// 저장본 식별값(ETag): 프로젝트 이름을 키로 마지막으로 본 값을 기억해, 다음 PUT/POST에 If-Match로 실어 보낸다
// (서버가 그사이 다른 창에서 저장됐으면 412로 막는다). 모듈 전역이라 테스트 사이에는 resetEtags()로 비운다
const etags = new Map<string, string>();

export function resetEtags(): void {
  etags.clear();
}

// 공통 알림 지점 (개정판 D3a-3, 계획 4.5). 저장 성공, 작업 등록 응답, 작업 종결을 화면 안 이벤트로 낸다.
// 진행 API 다시 조회(D3a-3)와 진행 작업 갱신(D3a-5), 다른 탭 알림(D3a-6)이 이것을 듣는다. 저장하지 않는 POST
// (실측, 미리 보기, 대조, 수치 검토)는 알리지 않도록 경로를 추측하지 않고 저장 경로마다 notify로 명시한다
// job_ended는 종결 상태를 싣는다: 작업 종결 알림이 성공, 실패, 취소, 중단을 다르게 알린다 (D3a-4, C23)
export type ProjectEvent = { kind: "saved" | "job_started" | "job_ended"; project: string; jobId?: string;
  state?: JobView["state"]; jobKind?: string };
const projectListeners = new Set<(event: ProjectEvent) => void>();

export function onProjectEvent(listener: (event: ProjectEvent) => void): () => void {
  projectListeners.add(listener);
  return () => { projectListeners.delete(listener); };
}

export function notifyProject(event: ProjectEvent): void {
  for (const listener of [...projectListeners]) {
    try { listener(event); } catch { /* 듣는 쪽의 오류가 요청을 실패로 만들지 않게 한다 */ }
  }
}

async function request<T>(
  path: string, init?: RequestInit,
  opts?: { etagKey?: string; updateEtag?: boolean; expectedEtag?: string; headers?: Record<string, string>;
    notify?: { kind: "saved" | "job_started"; project: string } },
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Requested-With": "SlideCaptain",  // 서버가 요구하는 앱 식별 헤더 (다른 사이트의 단순 요청 차단)
    ...opts?.headers,
  };
  const known = opts?.expectedEtag ?? (opts?.etagKey ? etags.get(opts.etagKey) : undefined);
  if (known) headers["If-Match"] = known;
  const r = await appFetch(path, { ...init, headers });
  await throwIfFailed(r);
  if (opts?.etagKey && opts.updateEtag !== false) {
    const etag = r.headers.get("ETag");
    if (etag) etags.set(opts.etagKey, etag);
  }
  const body = await r.json() as T;
  // 등록 응답을 받은 뒤에만 알린다. 그 전에 알리면 듣는 쪽의 조회가 빈 결과를 받는다 (계획 4.5)
  if (opts?.notify) {
    const id = (body as { id?: unknown } | null)?.id;
    notifyProject({ ...opts.notify, jobId: opts.notify.kind === "job_started" && typeof id === "string" ? id : undefined });
  }
  return body;
}

const enc = encodeURIComponent;

// 마지막으로 본 저장 ETag. 기준 저장본을 받는 작업(도식, 재작성, 수리)의 등록이 동의 전에 고정한다
export function savedEtag(name: string): string | undefined {
  return etags.get(name);
}

async function aiHeaders(): Promise<Record<string, string>> {
  const status = await api.getStatus();
  // 화면이 만드는 오류에도 원인 코드를 붙여 실패 안내가 원인별로 판정한다 (D3a-4 리뷰 R1). 확인하지 못함은
  // 서버의 상태 확인이 가른 코드(CLI 없음, 시간 초과, 구독 로그인 아님)를 따른다
  if (status.provider === "none") {
    throw new ApiError(503, "AI 연결이 설정되어 있지 않습니다.", "provider_missing");
  }
  if (status.login.logged_in === false) {
    throw new ApiError(503, "AI 연결에 로그인되어 있지 않습니다.", "login_required");
  }
  if (status.login.logged_in !== true) {
    throw new ApiError(503, status.login.error ?? "AI 연결 상태를 확인하지 못했습니다.",
      status.login.error_code ?? "provider_call_failed");
  }
  if ((status.provider === "claude" || status.provider === "chatgpt") && !status.selection_id) {
    throw new ApiError(503, "AI 설정을 확인하지 못했습니다. 앱을 다시 실행해 주세요.", "settings_unreadable");
  }
  if (!(await ensureConsent(status.selection_id ?? "legacy", status))) throw new AiConsentDeclined();
  return { "X-AI-Consent": "SlideCaptain", ...(status.selection_id ? { "X-AI-Selection": status.selection_id } : {}) };
}

// 작업 원장 (개정판 D2b-5a, 계획서 5.9). 종결 상태가 되면 조회를 멈춘다
export const TERMINAL_JOB_STATES = new Set(["succeeded", "failed", "cancelled", "interrupted", "remote_completion_unknown"]);

// 요청 ID는 사용자가 버튼을 누를 때 한 번 만든다. 응답을 받지 못한 재시도에만 같은 ID를 쓴다 (계획서 5.9)
export function newRequestId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

function pause(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(signal.reason); return; }
    const timer = setTimeout(() => { signal?.removeEventListener("abort", stop); resolve(); }, ms);
    const stop = () => { clearTimeout(timer); reject(signal?.reason); };
    signal?.addEventListener("abort", stop, { once: true });
  });
}

// 앞 응답을 받은 뒤 다음 조회를 예약한다. 조회가 실패하면 onError로 알리고 계속 조회한다 (계획서 5.9).
// 간격은 인자로 받아 시험에서 바꿀 수 있게 한다
// 조회 함수는 호출하는 쪽이 넘긴다: 화면이 쓰는 api 객체(시험에서는 모의)로 조회하게 하려는 것이다
export async function followJob(
  fetchJob: () => Promise<JobView>, onUpdate: (view: JobView) => void | Promise<void>,
  opts: { intervalMs?: number; signal?: AbortSignal; onError?: (error: unknown) => void } = {},
): Promise<JobView> {
  const intervalMs = opts.intervalMs ?? 1000;
  for (;;) {
    opts.signal?.throwIfAborted();
    try {
      const view = await fetchJob();
      await onUpdate(view);
      if (TERMINAL_JOB_STATES.has(view.state)) {
        notifyProject({ kind: "job_ended", project: view.project, jobId: view.id, state: view.state, jobKind: view.kind });
        return view;
      }
    } catch (error) {
      if (opts.signal?.aborted) throw error;
      opts.onError?.(error);
    }
    await pause(intervalMs, opts.signal);
  }
}

export const api = {
  listProjects: () => request<ProjectInfo[]>("/api/projects"),
  createProject: (name: string, title: string) =>
    request<ProjectInfo>("/api/projects", { method: "POST", body: JSON.stringify({ name, title }) }),
  getDeck: (name: string) => request<Deck>(`/api/projects/${enc(name)}/deck`, undefined, { etagKey: name }),
  putDeck: (name: string, deck: Deck, snapshot: boolean) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/deck?snapshot=${snapshot}`, {
      method: "PUT", body: JSON.stringify(deck),
    }, { etagKey: name, notify: { kind: "saved", project: name } }),
  measure: (deck: Deck, projectName?: string) =>
    request<RenderPlan>(projectName ? `/api/projects/${enc(projectName)}/render-plan` : "/api/render-plan", { method: "POST", body: JSON.stringify(deck) }),
  // 확인은 저장본을 바꾸지 않는다. 취소한 요청의 늦은 응답이 이후 저장의 ETag를 되돌리면 안 된다.
  reconcileDiagramStory: (name: string, req: ReconcileDiagramRequest) =>
    request<Deck>(`/api/projects/${enc(name)}/story-plan/diagram`, {
      method: "POST", body: JSON.stringify(req),
    }, { etagKey: name, updateEtag: false }),
  getDocumentChangeBasis: (name: string) =>
    request<DocumentChangeBasis>(`/api/projects/${enc(name)}/document-changes/basis`, {cache:"no-store"}, {etagKey:name,updateEtag:false}),
  previewDocumentChange: (name: string, req: DocumentChangeRequest, etag: string) =>
    request<DocumentChangePreview>(`/api/projects/${enc(name)}/document-changes/preview`, {method:"POST",body:JSON.stringify(req)}, {expectedEtag:etag}),
  applyDocumentChange: (name: string, req: DocumentChangeApplyRequest, etag: string) =>
    request<Deck>(`/api/projects/${enc(name)}/document-changes/apply`, {method:"POST",body:JSON.stringify(req)}, {etagKey:name,expectedEtag:etag,notify:{kind:"saved",project:name}}),
  previewEvidenceMigration: (name: string, req: EvidenceMigrationRequest, etag: string) =>
    request<DocumentChangePreview>(`/api/projects/${enc(name)}/evidence-migrations/preview`, {method:"POST",body:JSON.stringify(req)}, {expectedEtag:etag}),
  applyEvidenceMigration: (name: string, req: EvidenceMigrationApplyRequest, etag: string) =>
    request<Deck>(`/api/projects/${enc(name)}/evidence-migrations/apply`, {method:"POST",body:JSON.stringify(req)}, {etagKey:name,expectedEtag:etag,notify:{kind:"saved",project:name}}),
  applyStoryRewrite: (name: string, result: Pick<StoryRewriteResult, "deck" | "sources_fingerprint" | "base_etag">) =>
    request<Deck>(`/api/projects/${enc(name)}/story-plan/rewrite/apply`, {
      method: "POST", body: JSON.stringify({ deck: result.deck, sources_fingerprint: result.sources_fingerprint }),
    }, { etagKey: name, expectedEtag: result.base_etag, notify: { kind: "saved", project: name } }),
  reviewNumbers: (name: string, deck: Deck) =>
    request<NumericReviewReport>(`/api/projects/${enc(name)}/review/numbers`, {
      method: "POST", body: JSON.stringify(deck),
    }),
  reviewSemantics: (name: string, deck: Deck) =>
    request<SemanticSuspectReport>(`/api/projects/${enc(name)}/review/semantics`, {
      method: "POST", body: JSON.stringify(deck),
    }),
  getPreset: () => request<Preset>("/api/preset"),
  putPreset: (preset: Preset) =>
    request<{ ok: boolean }>("/api/preset", { method: "PUT", body: JSON.stringify(preset) }),
  listSources: (name: string) => request<string[]>(`/api/projects/${enc(name)}/sources`),
  readSource: (name: string, file: string) =>
    request<{ text: string }>(`/api/projects/${enc(name)}/sources/${enc(file)}`),
  writeSource: (name: string, file: string, text: string) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/sources/${enc(file)}`, {
      method: "PUT", body: JSON.stringify({ text }),
    }, { notify: { kind: "saved", project: name } }),
  uploadSource: async (name: string, file: File, overwrite: boolean) => {
    // 파일 본문을 원시 바이트로 보낸다. request()의 JSON 헤더를 붙이지 않는다 (서버는 Content-Type을 보지 않는다)
    // X-Requested-With: 서버가 이 헤더를 요구해 다른 사이트에서 보내는 단순 요청을 막는다 (JSON 헤더는 붙이지 않는다)
    const r = await appFetch(
      `/api/projects/${enc(name)}/sources/${enc(file.name)}/upload?overwrite=${overwrite}`,
      { method: "POST", body: file, headers: { "X-Requested-With": "SlideCaptain" } },
    );
    await throwIfFailed(r);
    const result = await r.json() as UploadResult;
    notifyProject({ kind: "saved", project: name });  // 업로드는 request()를 거치지 않으므로 여기서 알린다
    return result;
  },
  getStatus: () => request<AppStatus>("/api/status"),
  // AI 전송 준비(로그인과 동의 확인). 승인 반영보다 먼저 불러, 동의를 거절하면 덱을 바꾸지 않는다 (D2b-5a)
  prepareAi: () => aiHeaders(),
  // 장 생성 묶음 등록. If-Match는 승인 반영 PUT이 갱신한 ETag다. 응답은 저장 ETag를 바꾸지 않는다
  startChapters: (name: string, chapterIds: string[], headers: Record<string, string>, requestId: string) =>
    request<JobView>(`/api/projects/${enc(name)}/jobs`, {
      method: "POST", body: JSON.stringify({ request_id: requestId, kind: "chapters", params: { chapter_ids: chapterIds } }),
    }, { etagKey: name, updateEtag: false, headers, notify: { kind: "job_started", project: name } }),
  getJob: (name: string, jobId: string) =>
    request<JobView>(`/api/projects/${enc(name)}/jobs/${enc(jobId)}`, { cache: "no-store" }),
  listJobs: (name: string) => request<JobView[]>(`/api/projects/${enc(name)}/jobs`, { cache: "no-store" }),
  cancelJob: (name: string, jobId: string) =>
    request<JobView>(`/api/projects/${enc(name)}/jobs/${enc(jobId)}/cancel`, { method: "POST" }),
  // 작업 등록 (D2b-5b). 기준 저장본을 받는 종류만 expectedEtag를 If-Match로 보낸다. 등록은 저장 ETag를 바꾸지 않는다
  startJob: (name: string, body: { request_id: string; kind: string; params: unknown }, headers: Record<string, string>,
    expectedEtag?: string) =>
    request<JobView>(`/api/projects/${enc(name)}/jobs`, { method: "POST", body: JSON.stringify(body) },
      { expectedEtag, headers, notify: { kind: "job_started", project: name } }),
  settleCandidate: (name: string, jobId: string, action: "applied" | "dismissed") =>
    request<JobView>(`/api/projects/${enc(name)}/jobs/${enc(jobId)}/candidate`, {
      method: "POST", body: JSON.stringify({ action }),
    }, { notify: { kind: "saved", project: name } }),
  // 묶음의 장 후보를 버린다 (D2b-4 리뷰 R5). 장 후보는 반영하지 않고 새 묶음으로 다시 생성한다
  dismissChapterCandidate: (name: string, jobId: string, chapterId: string) =>
    request<JobView>(`/api/projects/${enc(name)}/jobs/${enc(jobId)}/candidate`, {
      method: "POST", body: JSON.stringify({ action: "dismissed", chapter_id: chapterId }),
    }, { notify: { kind: "saved", project: name } }),
  getActiveJob: () => request<ActiveJobStatus>("/api/jobs/active", { cache: "no-store" }),
  getAISettings: () => request<AISettings>("/api/ai/settings"),
  selectAI: (selection: AISelection) => request<AISelection>("/api/ai/selection", {
    method: "PUT", body: JSON.stringify(selection),
  }),
  startAILogin: (provider: ProviderId) => request<LoginAttempt>(`/api/ai/providers/${provider}/login`, { method: "POST" }),
  getAILogin: (provider: ProviderId) => request<LoginAttempt>(`/api/ai/providers/${provider}/login`),
  cancelAILogin: (provider: ProviderId) => request<LoginAttempt>(`/api/ai/providers/${provider}/login`, { method: "DELETE" }),
  listSnapshots: (name: string) => request<SnapshotInfo[]>(`/api/projects/${enc(name)}/snapshots`),
  // 충돌이나 저장 실패로 반영하지 못한 덱의 보존 (D2a-2). 기준 저장본은 마지막으로 본 ETag다.
  // 보존은 저장본을 바꾸지 않으므로 ETag를 진전시키지 않는다
  saveDraft: (name: string, req: { reason: DraftReason; source: DraftSource; deck: Deck }) =>
    request<DraftInfo>(`/api/projects/${enc(name)}/drafts`, {
      method: "POST", body: JSON.stringify({ ...req, base_etag: etags.get(name) ?? null }),
    }),
  listDrafts: (name: string) => request<DraftInfo[]>(`/api/projects/${enc(name)}/drafts`),
  // 단계 준비 상태 (D2a-6). 화면 연결은 D3에서 한다
  getProgress: (name: string) =>
    request<ProjectProgress>(`/api/projects/${enc(name)}/progress`, { cache: "no-store" }),
  restoreDraft: (name: string, id: string) =>
    request<Deck>(`/api/projects/${enc(name)}/drafts/${enc(id)}/restore`, { method: "POST" },
      { etagKey: name, notify: { kind: "saved", project: name } }),
  deleteDraft: (name: string, id: string) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/drafts/${enc(id)}`, { method: "DELETE" }),
  createSnapshot: (name: string) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/snapshots`, { method: "POST" }),
  restoreSnapshot: (name: string, id: string) =>
    request<Deck>(`/api/projects/${enc(name)}/snapshots/${enc(id)}/restore`, { method: "POST" },
      { etagKey: name, notify: { kind: "saved", project: name } }),
  exportDeck: (name: string) =>
    request<ExportResult>(`/api/projects/${enc(name)}/export`, { method: "POST" }, { notify: { kind: "saved", project: name } }),
  listExports: (name: string, offset = 0, limit = 20) =>
    request<ExportHistoryPage>(`/api/projects/${enc(name)}/exports?offset=${offset}&limit=${limit}`, { cache: "no-store" }),
  getExport: (name: string, id: string) =>
    request<ExportHistoryDetail>(`/api/projects/${enc(name)}/exports/${enc(id)}`, { cache: "no-store" }),
  getExportReviews: (name: string, id: string) =>
    request<ExportReviews>(`/api/projects/${enc(name)}/exports/${enc(id)}/reviews`, { cache: "no-store" }),
  getExportQualification: (name: string, id: string) =>
    request<ExportQualification>(`/api/projects/${enc(name)}/exports/${enc(id)}/qualification`, { cache: "no-store" }),
  renderExport: (name: string, id: string, input: QualificationRequest, baseEtag: string) =>
    request<ExportQualification>(`/api/projects/${enc(name)}/exports/${enc(id)}/render`, {
      method: "POST", body: JSON.stringify(input),
    }, { expectedEtag: baseEtag }),
  importIndependentReview: (name: string, id: string, input: IndependentReviewRequest, baseEtag: string) =>
    request<ExportQualification>(`/api/projects/${enc(name)}/exports/${enc(id)}/independent-reviews`, {
      method: "POST", body: JSON.stringify(input),
    }, { expectedEtag: baseEtag }),
  publishFinal: (name: string, id: string, input: QualificationRequest, baseEtag: string) =>
    request<FinalPublication>(`/api/projects/${enc(name)}/exports/${enc(id)}/publish-final`, {
      method: "POST", body: JSON.stringify(input),
    }, { expectedEtag: baseEtag }),
  recordExportReview: async (name: string, id: string, input: ExportReviewRequest, baseEtag: string) => {
    // 검수자가 실제로 열어 본 기준을 보낸다. 편집기의 ETag 캐시를 참조하거나 진전시키지 않는다.
    if (!baseEtag.trim()) throw new ApiError(428, "검수 기준을 다시 확인해 주세요.");
    return request<ExportReviews>(`/api/projects/${enc(name)}/exports/${enc(id)}/reviews`, {
      method: "POST", body: JSON.stringify(input),
    }, { expectedEtag: baseEtag, notify: { kind: "saved", project: name } });
  },
};
