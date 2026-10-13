// 장 후보 비교 화면의 시험 도우미 (D3c-6). 미리 보기 응답을 만들고, 화면에서 비교 화면을 거쳐 반영하는 사용자 동작을 흉내 낸다
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CandidateApplyPreview, Slide, Slots } from "../api/client";
import { planWith } from "./fixtures";

export function previewOf(current: Slide | null, candidate: Slots, over: Partial<CandidateApplyPreview> = {}): CandidateApplyPreview {
  const chapterId = current?.chapter_id ?? "c1";
  const plan = planWith(["미리보기"]);
  return {
    job_id: "job-1", chapter_id: chapterId, kind: "chapter", base_etag: "e0", blocked_reasons: [], notices: [],
    units: candidate.template === "bullet_box" ? ["bullets", "conclusion", "footnote"] : [], edited_units: null,
    keep_current: [], drop_edits: [], unhide: [], length_changed_units: [], current,
    merged: { chapter_id: chapterId, eyebrow: current?.eyebrow ?? "", subtitle: current?.subtitle ?? "", slots: candidate },
    warnings: [], removed_edits: [], unhidden: [], removed_spans: 0, removed_chart: false, already_applied: false,
    page_width_pt: 960, page_height_pt: 540, style: plan.style, current_plan: current ? plan.slides[0] : null,
    merged_plan: plan.slides[0], ...over,
  } as CandidateApplyPreview;
}

export const compareDialog = () => screen.findByRole("dialog", { name: /새 내용과 비교/ });

// 패널의 "비교하고 반영"을 누르고 비교 화면의 "반영"을 누른다
export async function applyThroughCompare(): Promise<void> {
  await userEvent.click(await screen.findByRole("button", { name: "비교하고 반영" }));
  const dialog = await compareDialog();
  const apply = await within(dialog).findByRole("button", { name: "반영" });
  await vi.waitFor(() => expect(apply).toBeEnabled());
  await userEvent.click(apply);
}
