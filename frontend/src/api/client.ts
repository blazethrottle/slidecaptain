import type { components } from "./types";

export type Deck = components["schemas"]["Deck"];
export type DeckMeta = components["schemas"]["DeckMeta"];
export type Chapter = components["schemas"]["Chapter"];
export type Structure = components["schemas"]["Structure"];
export type Slide = components["schemas"]["Slide"];
export type Slots = Slide["slots"];
export type Bullet = components["schemas"]["Bullet"];  // level이 필수 필드다 (기본값이 있어도 생성 타입에서는 필수)
export type Preset = components["schemas"]["Preset"];
export type ProjectInfo = components["schemas"]["ProjectInfo"];
export type SnapshotInfo = components["schemas"]["SnapshotInfo"];
export type RenderPlan = components["schemas"]["RenderPlan"];
export type SlidePlan = components["schemas"]["SlidePlan"];
export type Frame = components["schemas"]["Frame"];
export type Para = components["schemas"]["Para"];
export type TablePlan = components["schemas"]["TablePlan"];
export type CapacityWarning = components["schemas"]["CapacityWarning"];
export type StructureResult = components["schemas"]["StructureResult"];
export type ChapterResult = components["schemas"]["ChapterResult"];
export type TemplateName = Chapter["template"];
export type UploadResult = components["schemas"]["UploadResult"];
export type AppStatus = components["schemas"]["AppStatus"];
export type LoginStatus = components["schemas"]["LoginStatus"];

export class ApiError extends Error {
  constructor(public status: number, detail: string) {
    super(detail);
  }
}

export function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : "서버에 연결하지 못했습니다. 앱을 다시 시작해 주세요.";
}

async function throwIfFailed(r: Response): Promise<void> {
  if (r.ok) return;
  let detail = "요청이 실패했습니다. 잠시 후 다시 시도해 주세요.";
  try {
    const body = await r.json();
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // JSON 본문이 아니면 기본 문구 유지
  }
  throw new ApiError(r.status, detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  await throwIfFailed(r);
  return r.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const api = {
  listProjects: () => request<ProjectInfo[]>("/api/projects"),
  createProject: (name: string, title: string) =>
    request<ProjectInfo>("/api/projects", { method: "POST", body: JSON.stringify({ name, title }) }),
  getDeck: (name: string) => request<Deck>(`/api/projects/${enc(name)}/deck`),
  putDeck: (name: string, deck: Deck, snapshot: boolean) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/deck?snapshot=${snapshot}`, {
      method: "PUT", body: JSON.stringify(deck),
    }),
  measure: (deck: Deck) =>
    request<RenderPlan>("/api/render-plan", { method: "POST", body: JSON.stringify(deck) }),
  getPreset: () => request<Preset>("/api/preset"),
  putPreset: (preset: Preset) =>
    request<{ ok: boolean }>("/api/preset", { method: "PUT", body: JSON.stringify(preset) }),
  listSources: (name: string) => request<string[]>(`/api/projects/${enc(name)}/sources`),
  readSource: (name: string, file: string) =>
    request<{ text: string }>(`/api/projects/${enc(name)}/sources/${enc(file)}`),
  writeSource: (name: string, file: string, text: string) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/sources/${enc(file)}`, {
      method: "PUT", body: JSON.stringify({ text }),
    }),
  uploadSource: async (name: string, file: File, overwrite: boolean) => {
    // 파일 본문을 원시 바이트로 보낸다. request()의 JSON 헤더를 붙이지 않는다 (서버는 Content-Type을 보지 않는다)
    // X-Requested-With: 서버가 이 헤더를 요구해 다른 사이트에서 보내는 단순 요청을 막는다 (JSON 헤더는 붙이지 않는다)
    const r = await fetch(
      `/api/projects/${enc(name)}/sources/${enc(file.name)}/upload?overwrite=${overwrite}`,
      { method: "POST", body: file, headers: { "X-Requested-With": "SlideCaptain" } },
    );
    await throwIfFailed(r);
    return r.json() as Promise<UploadResult>;
  },
  getStatus: () => request<AppStatus>("/api/status"),
  listSnapshots: (name: string) => request<SnapshotInfo[]>(`/api/projects/${enc(name)}/snapshots`),
  createSnapshot: (name: string) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/snapshots`, { method: "POST" }),
  restoreSnapshot: (name: string, id: string) =>
    request<Deck>(`/api/projects/${enc(name)}/snapshots/${enc(id)}/restore`, { method: "POST" }),
  exportDeck: (name: string) =>
    request<{ path: string }>(`/api/projects/${enc(name)}/export`, { method: "POST" }),
  generateStructure: (name: string, req: { target_chapters?: number | null; instructions?: string }) =>
    request<StructureResult>(`/api/projects/${enc(name)}/generate/structure`, {
      method: "POST", body: JSON.stringify(req),
    }),
  generateChapter: (name: string, chapterId: string, instructions = "") =>
    request<ChapterResult>(`/api/projects/${enc(name)}/generate/chapter/${enc(chapterId)}`, {
      method: "POST", body: JSON.stringify({ instructions }),
    }),
  condenseChapter: (name: string, chapterId: string, slots: Slots, instructions = "") =>
    request<ChapterResult>(`/api/projects/${enc(name)}/generate/chapter/${enc(chapterId)}/condense`, {
      method: "POST", body: JSON.stringify({ slots, instructions }),
    }),
};
