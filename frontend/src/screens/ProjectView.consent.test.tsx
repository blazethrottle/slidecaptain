// AI 전송 고지 관문의 화면 통합 검증 (계획서 B3). 이 파일만 api를 목 처리하지 않고 fetch를
// 스텁해 client.ts의 실제 관문 배선(ensureConsent)이 화면까지 이어지는지 확인한다. 다른
// ProjectView 테스트 파일은 api를 통째로 mock 처리해 이 경로를 검증하지 못한다 (계획서 B3 리뷰).
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { revokeConsent } from "../api/aiGate";
import type { AppStatus, Deck } from "../api/client";
import { ProjectView } from "./ProjectView";

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

function emptyDeck(): Deck {
  return {
    schema_version: 1,
    meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
    structure: { chapters: [] },
    slides: [],
  };
}

const STATUS: AppStatus = {
  provider: "subscription", model: "sonnet", last_generation_at: null, checked_at: "2026-09-04T09:00:00+09:00",
  login: { logged_in: true, auth_method: "claude.ai", account: "co***@example.com", cli_version: null, error: null },
};

function stubFetch(): ReturnType<typeof vi.fn> {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    if (method === "GET" && url.endsWith("/api/projects/p1/deck")) {
      return new Response(JSON.stringify(emptyDeck()), { status: 200, headers: { ETag: '"e1"' } });
    }
    if (method === "GET" && url.endsWith("/api/projects/p1/sources")) {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    if (method === "GET" && url.endsWith("/api/status")) {
      return new Response(JSON.stringify(STATUS), { status: 200 });
    }
    if (method === "POST" && url.endsWith("/generate/structure")) {
      return new Response(JSON.stringify({
        status: "ok", structure: { chapters: [] }, raw_text: "", unverified_numbers: [], format_retried: false,
      }), { status: 200 });
    }
    throw new Error(`스텁되지 않은 요청: ${method} ${url}`);
  });
}

beforeEach(() => { revokeConsent(); });
afterEach(() => { vi.unstubAllGlobals(); });

async function openStructureTab() {
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "구조안" }));
  await screen.findByRole("button", { name: "구조안 생성" });
}

it("첫 구조안 생성 클릭에 대화 상자가 뜨고, 취소하면 요청이 나가지 않고 알림이 아닌 안내가 뜬다", async () => {
  const fetchMock = stubFetch();
  vi.stubGlobal("fetch", fetchMock);
  await openStructureTab();
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByRole("dialog");
  // 대화 상자가 열린 동안 탭 버튼이 잠긴다 (계획서 B3)
  expect(screen.getByRole("button", { name: "자료" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "구조안" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "취소" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getByRole("button", { name: "자료" })).not.toBeDisabled();
  expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/generate/structure"))).toBe(false);
  const notice = await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(notice.closest('[role="alert"]')).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("동의하면 요청이 나가고 대화 상자가 닫히며, 두 번째 클릭에는 다시 뜨지 않는다", async () => {
  const fetchMock = stubFetch();
  vi.stubGlobal("fetch", fetchMock);
  await openStructureTab();
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByRole("dialog");
  await userEvent.click(screen.getByRole("button", { name: "전송에 동의하고 계속" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/generate/structure"))).toBe(true);
  // 두 번째 클릭은 이미 동의한 탭이라 대화 상자 없이 곧장 나간다 (스텁 응답이 빈 구조안이라
  // 버튼 문구는 그대로 "구조안 생성"이다)
  const before = fetchMock.mock.calls.length;
  await userEvent.click(await screen.findByRole("button", { name: "구조안 생성" }));
  await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(before));
  expect(screen.queryByRole("dialog")).toBeNull();
});
