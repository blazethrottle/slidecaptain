import { readFileSync } from "node:fs";
const template = readFileSync("../scripts/windows-review-form.html", "utf8");

const manifest = {
  created_at: "2026-10-19T00:00:00Z", git_commit: "test-commit", worktree_dirty: false,
  artifacts: [{ id: "bar", title: "합성 비교", file: "bar.pptx", sha256: "bar-hash", focus: "차트", pages: [{ page: 1, topic: "비교" }] }],
  targeted_review: { version: "c3-t4-v1", checks: [
    { id: "bar-axis", title: "가로 막대 축", artifact_id: "bar", page: 1, instruction: "아래 축 확인", expected: "1pt 안" },
    { id: "status-icon", title: "상태 아이콘", artifact_id: null, page: null, instruction: "앱에서 확인", expected: "‼︎ 표시" },
  ] },
};

function openForm() {
  const iframe = document.createElement("iframe");
  document.body.append(iframe);
  const doc = iframe.contentDocument;
  const html = template.replace("__REVIEW_MANIFEST__", JSON.stringify(manifest));
  doc.documentElement.innerHTML = html;
  const script = doc.querySelector("script").textContent;
  const api = new Function("document", "localStorage", script + "; return {collect, restore};")(doc, localStorage);
  return { doc, ...api };
}

function editCheck(doc, id, verdict, note) {
  const check = doc.querySelector(`[data-check="${id}"]`);
  check.querySelector("select").value = verdict;
  const textarea = check.querySelector("textarea");
  textarea.value = note;
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

afterEach(() => { document.body.innerHTML = ""; localStorage.clear(); });

it("확인 항목은 미평가로 시작하고 대상 페이지와 확인 방법을 표시한다", () => {
  const { doc, collect } = openForm();
  expect(doc.querySelectorAll("[data-check]")).toHaveLength(2);
  expect(doc.querySelector('[data-check="bar-axis"]').textContent).toContain("1쪽");
  expect(doc.querySelector('[data-check="bar-axis"]').textContent).toContain("아래 축 확인");
  expect(collect().targeted_review.checks).toEqual([
    { id: "bar-axis", artifact_id: "bar", artifact_sha256: "bar-hash", page: 1, verdict: null, note: null },
    { id: "status-icon", artifact_id: null, artifact_sha256: null, page: null, verdict: null, note: null },
  ]);
});

it("항목 판정과 메모를 JSON 및 브라우저 임시 저장에서 복원한다", () => {
  const first = openForm();
  editCheck(first.doc, "bar-axis", "needs_revision", "축이 위에 있음");
  const feedback = JSON.parse(JSON.stringify(first.collect()));
  const second = openForm();
  expect(second.collect().targeted_review).toEqual(feedback.targeted_review);
  editCheck(second.doc, "bar-axis", "pass", "바뀐 메모");
  second.restore(feedback);
  expect(second.collect().targeted_review).toEqual(feedback.targeted_review);
});

it("이전 JSON을 불러오면 새 확인 항목을 미평가로 지우고 기존 판정을 유지한다", () => {
  const { doc, collect, restore } = openForm();
  editCheck(doc, "bar-axis", "pass", "현재 메모");
  const old = collect();
  delete old.targeted_review;
  old.evaluations[0].criteria.visual = "needs_revision";
  restore(old);
  expect(collect().targeted_review.checks.every(c => c.verdict === null && c.note === null)).toBe(true);
  expect(collect().evaluations[0].criteria.visual).toBe("needs_revision");
});

it.each(["run", "hash", "version", "page", "duplicate", "missing", "artifact", "pages", "verdict"])("%s 불일치 피드백은 기존 입력을 바꾸기 전에 거절한다", (kind) => {
  const { doc, collect, restore } = openForm();
  editCheck(doc, "bar-axis", "needs_revision", "현재 입력 보존");
  const before = collect();
  const invalid = JSON.parse(JSON.stringify(before));
  invalid.environment.reviewer = "다른 검수자";
  if (kind === "run") invalid.run_created_at = "다른 회차";
  if (kind === "hash") invalid.targeted_review.checks[0].artifact_sha256 = "다른 파일";
  if (kind === "version") invalid.targeted_review.version = "future-version";
  if (kind === "page") invalid.targeted_review.checks[0].page = 2;
  if (kind === "duplicate") invalid.targeted_review.checks.push(invalid.targeted_review.checks[0]);
  if (kind === "missing") invalid.targeted_review.checks.pop();
  if (kind === "artifact") invalid.evaluations[0].artifact_sha256 = "다른 표본";
  if (kind === "pages") invalid.evaluations[0].pages = {};
  if (kind === "verdict") invalid.targeted_review.checks[0].verdict = "automatic_pass";
  expect(() => restore(invalid)).toThrow();
  const after = collect();
  expect(after.environment).toEqual(before.environment);
  expect(after.targeted_review).toEqual(before.targeted_review);
});

it("실제 JSON 저장 버튼이 새 항목의 판정과 표본 해시를 내려보낸다", async () => {
  const { doc } = openForm();
  editCheck(doc, "bar-axis", "needs_revision", "측정 2pt");
  let downloaded;
  const original = URL.createObjectURL;
  URL.createObjectURL = vi.fn(blob => { downloaded = blob; return "blob:feedback"; });
  const click = vi.spyOn(doc.defaultView.HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  try {
    const timer = vi.spyOn(globalThis, "setTimeout").mockReturnValue(0);
    try { doc.querySelector("#save").click(); } finally { timer.mockRestore(); }
    const text = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsText(downloaded);
    });
    const feedback = JSON.parse(text);
    expect(feedback.targeted_review.checks[0]).toMatchObject({ artifact_sha256: "bar-hash", verdict: "needs_revision", note: "측정 2pt" });
    expect(feedback.targeted_review.checks[1].verdict).toBeNull();
    expect(click).toHaveBeenCalledOnce();
  } finally { URL.createObjectURL = original; click.mockRestore(); }
});
