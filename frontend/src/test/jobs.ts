// 작업 원장 응답의 시험용 생성기 (개정판 D2b-5a)
import type { ChapterView, GenerationUsage, JobView, Slots } from "../api/client";
import { emptyUsage } from "./usage";

export function chapterResult(slots: Slots | null, usage: GenerationUsage = emptyUsage(),
  extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { status: slots ? "ok" : "format_error", slots, usage, raw_text: "", warnings: [], unverified_numbers: [],
    format_retried: false, condensed: false, ...extra };
}

export function chapterView(chapterId: string, state: ChapterView["state"],
  extra: Partial<ChapterView> = {}): ChapterView {
  return { chapter_id: chapterId, position: 0, state, candidate_status: state === "succeeded" ? "applied" : "none",
    error: null, result: null, started_at: null, finished_at: null, ...extra };
}

export function batchView(chapters: ChapterView[], extra: Partial<JobView> = {}): JobView {
  return {
    id: "job-1", project: "p1", kind: "chapters", state: "succeeded", target: null, params: {},
    candidate_status: "none", outcome: "all_applied", owner: "this_instance", created_at: "2026-10-08T10:00:00+09:00",
    started_at: null, finished_at: null, provider: null, model: null, base_etag: null, current_etag: null,
    relevance_hash: null, stale_reasons: [], cancel_requested: false, error: null, result: null,
    chapters: chapters.map((c, i) => ({ ...c, position: i })), ...extra,
  };
}
