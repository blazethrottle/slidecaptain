import type { ExportReviewRecord, ExportReviews } from "../api/client";

export const reviewCategories = ["narrative", "evidence", "representation", "visual", "target_renderer"] as const;

export function exportReviews(overrides: Partial<ExportReviews> = {}): ExportReviews {
  return {
    export_id: "report_v001", checked_at: "2026-09-29T10:00:00+00:00", base_etag: '"opened-deck"',
    input_fingerprint: "a".repeat(64), artifact_sha256: "b".repeat(64),
    current_input_fingerprint: "a".repeat(64), slide_count: 2, status: "current", storage_status: "empty",
    can_record: true, reason: null,
    categories: reviewCategories.map(category => ({ category, status: "not_run", latest_record_id: null })),
    records: [], final_export_allowed: false, ...overrides,
  };
}

export function reviewRecord(overrides: Partial<ExportReviewRecord> = {}): ExportReviewRecord {
  return {
    id: "review-1", sequence: 1, rule_version: "manual-review-v1", export_id: "report_v001",
    input_fingerprint: "a".repeat(64), artifact_sha256: "b".repeat(64), reviewed_at: "2026-09-29T10:01:00+00:00",
    category: "narrative", status: "passed", reviewer: "합성 검수자", note: "합성 QA 기록입니다.", pages: [1, 2],
    ...overrides,
  };
}
