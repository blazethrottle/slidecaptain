// 상태 표시 컴포넌트 (개정판 D2a-5). 색 없이도 문구와 아이콘으로 상태를 구별한다.
import { act, render, screen } from "@testing-library/react";
import { SaveAnnouncer, STATUS_KINDS, StatusIndicator, saveStatusKind } from "./StatusIndicator";

it("상태 10종은 문구와 아이콘의 접근 가능한 이름이 모두 다르다", () => {
  const labels = new Set<string>();
  const icons = new Set<string>();
  for (const kind of STATUS_KINDS) {
    const { container, unmount } = render(<StatusIndicator kind={kind} />);
    const icon = container.querySelector('[role="img"]')!;
    icons.add(icon.getAttribute("aria-label")!);
    labels.add(container.querySelector(".status-label")!.textContent!);
    unmount();
  }
  expect(STATUS_KINDS).toHaveLength(10);
  expect(labels.size).toBe(10);
  expect(icons.size).toBe(10);
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
  for (const kind of ["unsaved", "saving", "save_failed", "conflict", "ready", "running"] as const) {
    const { container, unmount } = render(<StatusIndicator kind={kind} />);
    expect(container.querySelector('[role="img"]')!.textContent).toMatch(/\uFE0E$/);
    unmount();
  }
});
