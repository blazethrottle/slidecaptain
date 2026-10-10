// 상태 표시 컴포넌트 (개정판 D2a-5). 색 없이도 문구와 아이콘으로 상태를 구별한다.
import { act, render, screen } from "@testing-library/react";
import { notifyProject } from "../api/client";
import { JobAnnouncer, SaveAnnouncer, STATUS_KINDS, StatusIndicator, saveStatusKind } from "./StatusIndicator";

it("상태 15종(작업 상태 2종, 단계 상태 3종 포함)은 문구와 아이콘의 접근 가능한 이름이 모두 다르다", () => {
  const labels = new Set<string>();
  const icons = new Set<string>();
  for (const kind of STATUS_KINDS) {
    const { container, unmount } = render(<StatusIndicator kind={kind} />);
    const icon = container.querySelector('[role="img"]')!;
    icons.add(icon.getAttribute("aria-label")!);
    labels.add(container.querySelector(".status-label")!.textContent!);
    unmount();
  }
  // 다시 씀(D3a-3): 단계 상태 3종(확인하지 못함, 작성 중, 초안 확인됨)을 더해 12종에서 15종으로
  expect(STATUS_KINDS).toHaveLength(15);
  expect(labels.size).toBe(15);
  expect(icons.size).toBe(15);
});

// D2a 이월 (7), D3a-1. 지금 코드의 틀린 동작: 접근 가능한 이름이 "빈 원", "연필" 같은 모양 이름이다.
// 이름은 상태의 뜻을 말하되 라벨 문구와 같지 않게 한다(화면 낭독기가 같은 말을 두 번 읽지 않게)
const ICON_NAMES: Record<(typeof STATUS_KINDS)[number], string> = {
  not_started: "아직 시작하지 않음",
  unsaved: "저장하지 않은 변경",
  saving: "저장 진행",
  saved: "저장 완료",
  save_failed: "저장 실패 경고",
  conflict: "저장 충돌",
  ready: "준비 완료",
  needs_review: "주의",
  failed: "오류",
  running: "진행 중",
  cancel_requested: "취소 대기",
  completion_unknown: "결과 불명",
  unknown: "상태 미확인",
  in_progress: "작성 진행",
  draft_checked: "초안 점검 통과",
};
const SHAPE_NAMES = ["빈 원", "연필", "회전 화살표", "체크", "경고 삼각형", "엇갈린 화살표", "체크 상자", "느낌표",
  "엑스", "진행 점", "일시 정지", "물음표"];

it("아이콘의 접근 가능한 이름은 모양이 아니라 상태의 뜻이고 라벨 문구와 다르다 (D2a 이월 7)", () => {
  for (const kind of STATUS_KINDS) {
    const { container, unmount } = render(<StatusIndicator kind={kind} />);
    const name = container.querySelector('[role="img"]')!.getAttribute("aria-label")!;
    expect(name).toBe(ICON_NAMES[kind]);
    expect(SHAPE_NAMES).not.toContain(name);
    // 라벨과 같거나 라벨의 일부이면 화면 낭독기가 같은 말을 두 번 읽는다 (D3a-1 리뷰 R21)
    expect(container.querySelector(".status-label")!.textContent).not.toContain(name);
    unmount();
  }
});

it("저장 상태와 충돌 여부를 표시 종류로 옮긴다", () => {
  expect(saveStatusKind("저장됨", false)).toBe("saved");
  expect(saveStatusKind("저장 대기", false)).toBe("unsaved");
  expect(saveStatusKind("저장 중", false)).toBe("saving");
  expect(saveStatusKind("저장 실패", false)).toBe("save_failed");
  expect(saveStatusKind("저장 실패", true)).toBe("conflict");
});

it("충돌과 저장 실패는 서로 다른 문구로 보인다", () => {
  const { rerender } = render(<StatusIndicator kind="save_failed" />);
  expect(screen.getByText(/변경은 이 화면에 남아 있습니다/)).toBeInTheDocument();
  rerender(<StatusIndicator kind="conflict" />);
  expect(screen.getByText("다른 곳에서 먼저 저장했습니다")).toBeInTheDocument();
});

it("보조 문구를 함께 보일 수 있다", () => {
  render(<StatusIndicator kind="running" detail="구성 생성 중" />);
  expect(screen.getByText("구성 생성 중")).toBeInTheDocument();
});

it("저장 알림은 저장됨으로 바뀔 때만 알리고 대기와 저장 중에는 바꾸지 않는다", () => {
  const { rerender } = render(<SaveAnnouncer kind="saved" />);
  const region = screen.getByRole("status");
  expect(region).toHaveTextContent("");  // 처음 그릴 때는 알리지 않는다
  rerender(<SaveAnnouncer kind="unsaved" />);
  expect(region).toHaveTextContent("");
  rerender(<SaveAnnouncer kind="saving" />);
  expect(region).toHaveTextContent("");
  act(() => { rerender(<SaveAnnouncer kind="saved" />); });
  expect(region).toHaveTextContent("저장됨");
});


it("충돌을 서버 내용으로 되돌린 뒤의 저장됨은 알리지 않는다 (D2a-5 리뷰 R10)", () => {
  const { rerender } = render(<SaveAnnouncer kind="unsaved" />);
  rerender(<SaveAnnouncer kind="conflict" />);
  act(() => { rerender(<SaveAnnouncer kind="saved" />); });
  expect(screen.getByRole("status")).toHaveTextContent("");
});

it("아이콘 글자는 색 이모지가 아니라 글자 모양으로 그리도록 요청한다 (D2a-5 리뷰 R13)", () => {
  for (const kind of ["unsaved", "saving", "save_failed", "conflict", "ready", "running", "in_progress", "draft_checked"] as const) {
    const { container, unmount } = render(<StatusIndicator kind={kind} />);
    expect(container.querySelector('[role="img"]')!.textContent).toMatch(/\uFE0E$/);
    unmount();
  }
});

it("작업 알림은 진행 중 작업이 사라질 때만 알린다 (D2b-5c)", () => {
  const a = { id: "job-a", project: "보고 A" };
  const { rerender, container } = render(<JobAnnouncer active={null} />);
  const status = () => container.querySelector('[role="status"]')!.textContent;
  expect(status()).toBe("");
  rerender(<JobAnnouncer active={a} />);
  expect(status()).toBe("");
  rerender(<JobAnnouncer active={{ ...a }} />);  // 조회마다 새 객체가 와도 같은 작업이면 알리지 않는다
  expect(status()).toBe("");
  rerender(<JobAnnouncer active={null} />);
  expect(status()).toBe("AI 생성 작업이 끝났습니다(보고 A)");
  // 다시 씀(D3a-4 리뷰 R11): 한 작업은 한 번만 알리므로 이미 알린 작업 대신 새 작업 c를 쓴다
  const c = { id: "job-c", project: "보고 C" };
  rerender(<JobAnnouncer active={c} />);
  rerender(<JobAnnouncer active={{ id: "job-b", project: "보고 B" }} />);  // 한 조회 간격 안에 다음 작업이 시작됐다
  expect(status()).toBe("AI 생성 작업이 끝났습니다(보고 C)");
});

it("같은 탭이 시작한 작업은 진행 작업 조회가 몰라도 종결 알림으로 결과를 알리고, 한 번만 알린다 (D3a-4 리뷰 R11)", () => {
  // 지금 코드의 틀린 동작: 진행 작업 조회에서 사라짐을 보지 못하면 아무것도 알리지 않는다
  const { rerender, container } = render(<JobAnnouncer active={null} />);
  const status = () => container.querySelector('[role="status"]')!.textContent;
  act(() => notifyProject({ kind: "job_ended", project: "보고 D", jobId: "job-d", state: "failed" }));
  expect(status()).toBe("AI 생성 작업이 실패했습니다(보고 D)");
  // 늦게 온 진행 작업 조회가 같은 작업의 사라짐을 보아도 다시 알리지 않는다
  rerender(<JobAnnouncer active={{ id: "job-d", project: "보고 D" }} />);
  rerender(<JobAnnouncer active={null} />);
  expect(status()).toBe("AI 생성 작업이 실패했습니다(보고 D)");
});

it("작업 알림은 성공, 실패, 취소, 중단, 완료 불명을 다른 문구로 알린다 (D3a-4, C23)", () => {
  const status = (container: HTMLElement) => container.querySelector('[role="status"]')!.textContent;
  const cases: [string, string][] = [
    ["succeeded", "AI 생성 작업이 끝났습니다(보고 A)"],
    ["failed", "AI 생성 작업이 실패했습니다(보고 A)"],
    ["cancelled", "AI 생성 작업을 취소했습니다(보고 A)"],
    ["interrupted", "AI 생성 작업이 중단되었습니다(보고 A)"],
    ["remote_completion_unknown", "AI 생성 작업이 끝났는지 확인하지 못했습니다(보고 A)"],
  ];
  for (const [state, text] of cases) {
    // 종결 알림이 진행 작업의 사라짐보다 먼저 온 경우
    const a = { id: `job-${state}`, project: "보고 A" };
    const first = render(<JobAnnouncer active={a} />);
    act(() => notifyProject({ kind: "job_ended", project: "보고 A", jobId: a.id, state: state as never }));
    first.rerender(<JobAnnouncer active={null} />);
    expect(status(first.container)).toBe(text);
    first.unmount();
    // 사라짐을 먼저 알리고 종결 알림이 뒤에 온 경우: 결과 문구로 고친다
    const b = { id: `job-late-${state}`, project: "보고 A" };
    const second = render(<JobAnnouncer active={b} />);
    second.rerender(<JobAnnouncer active={null} />);
    expect(status(second.container)).toBe("AI 생성 작업이 끝났습니다(보고 A)");
    act(() => notifyProject({ kind: "job_ended", project: "보고 A", jobId: b.id, state: state as never }));
    expect(status(second.container)).toBe(text);
    second.unmount();
  }
});

it("작업 상태 2종의 색조와 글자 모양 아이콘 (D2b-5c)", () => {
  const { container, rerender } = render(<StatusIndicator kind="cancel_requested" />);
  expect(container.querySelector(".status-neutral")).not.toBeNull();
  expect(container.querySelector('[role="img"]')!.textContent).toBe("\u23F8\uFE0E");  // 색 이모지가 아닌 글자 모양
  rerender(<StatusIndicator kind="completion_unknown" />);
  expect(container.querySelector(".status-warning")).not.toBeNull();
});

it("저장 상태를 보이지 않는 때(null)를 거친 저장됨은 알리지 않는다 (D3a-2 리뷰 R2)", () => {
  // 저장 없이 단계를 떠나면 미저장에서 null로, 다음 단계가 저장됨을 올린다. 이 바뀜은 저장이 아니다
  const { rerender } = render(<SaveAnnouncer kind="unsaved" />);
  rerender(<SaveAnnouncer kind={null} />);
  act(() => { rerender(<SaveAnnouncer kind="saved" />); });
  expect(screen.getByRole("status")).toHaveTextContent("");
  // null 다음의 미저장에서 저장으로 바뀌면 알린다
  rerender(<SaveAnnouncer kind="unsaved" />);
  act(() => { rerender(<SaveAnnouncer kind="saved" />); });
  expect(screen.getByRole("status")).toHaveTextContent("저장됨");
});

it("같은 결과의 작업이 연달아 끝나도 작업 종류가 글에 들어가 두 번째도 알린다 (D3a 묶음 리뷰 A1)", () => {
  // 지금 코드의 틀린 동작: 구조안 생성 성공 뒤 내용 생성 성공은 글이 같아 화면 낭독기가 다시 읽지 않는다
  const { container } = render(<JobAnnouncer active={null} />);
  const status = () => container.querySelector('[role="status"]')!.textContent;
  act(() => notifyProject({ kind: "job_ended", project: "보고 E", jobId: "job-s", state: "succeeded", jobKind: "structure" }));
  expect(status()).toBe("구조안 생성이 끝났습니다(보고 E)");
  act(() => notifyProject({ kind: "job_ended", project: "보고 E", jobId: "job-c", state: "succeeded", jobKind: "chapters" }));
  expect(status()).toBe("내용 생성이 끝났습니다(보고 E)");
});
