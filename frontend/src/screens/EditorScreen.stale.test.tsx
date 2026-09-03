// 낡은 미리보기 편집 차단과 실측 오류 분리 (2026-09-03 저장 안전성 묶음 태스크 B)
// 배경: 미리보기가 편집 대상 인덱스를 서버 렌더 계획에서 가져오는데, 덱이 바뀐 뒤 새 계획이 오기까지
// 낡은 계획이 편집 가능한 채로 남아 다른 불릿을 덮어썼다(FC-05). 실측 오류가 저장 성공에 지워졌다(FC-02).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError } from "../api/client";
import { bulletsOf, deckWith, deferred, planWith, preset, project } from "../test/fixtures";
import { EditorScreen } from "./EditorScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn() } };
});

const preview = () => within(document.querySelector(".editor-center") as HTMLElement);

it("불릿 삭제 뒤 새 계획이 오기 전에는 낡은 문단을 클릭해도 편집이 열리지 않고, 새 계획이 오면 올바른 불릿에 저장된다 (FC-05)", async () => {
  const second = deferred<ReturnType<typeof planWith>>();
  vi.mocked(api.measure).mockResolvedValueOnce(planWith(["A", "B", "C"]))
    .mockImplementationOnce(() => second.promise)
    .mockResolvedValue(planWith(["B2", "C"]));
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  render(<EditorScreen project={project} deck={deckWith(["A", "B", "C"])} onDeckChange={() => {}}
    timings={{ measureMs: 0, saveMs: 0 }} />);
  await preview().findByText("B");
  await userEvent.click(preview().getByText("B"));  // 프레임 선택
  await userEvent.click(screen.getByRole("button", { name: "본문 불릿 1 삭제" }));  // A 삭제, 덱 [B, C]
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  expect(bulletsOf(vi.mocked(api.putDeck).mock.calls[0][1])).toEqual(["B", "C"]);

  // 낡은 계획([A, B, C])이 흐림 표시로 남아 있고, 문단을 클릭해도 편집 입력이 열리지 않는다
  expect(document.querySelector(".preview-canvas")).toHaveClass("stale");
  await userEvent.click(preview().getByText("B"));
  expect(screen.queryByLabelText("내용 수정")).toBeNull();
  expect(api.putDeck).toHaveBeenCalledTimes(1);

  // 새 계획이 도착하면 편집이 열리고 올바른 불릿(B)이 고쳐진다
  second.resolve(planWith(["B", "C"]));
  await waitFor(() => expect(document.querySelector(".preview-canvas")).not.toHaveClass("stale"));
  await userEvent.click(preview().getByText("B"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "B2{Enter}");
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(2));
  expect(bulletsOf(vi.mocked(api.putDeck).mock.calls[1][1])).toEqual(["B2", "C"]);
});

it("실측 실패는 저장 성공에 지워지지 않고, '다시 그리기' 로 재실측한다 (FC-02)", async () => {
  vi.mocked(api.measure).mockResolvedValueOnce(planWith(["하나"]))
    .mockRejectedValueOnce(new ApiError(500, "실측 실패"))
    .mockResolvedValue(planWith(["둘"]));
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  render(<EditorScreen project={project} deck={deckWith(["하나"])} onDeckChange={() => {}}
    timings={{ measureMs: 0, saveMs: 0 }} />);
  await preview().findByText("하나");
  await userEvent.click(preview().getByText("하나"));
  await userEvent.click(preview().getByText("하나"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "둘{Enter}");
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  await screen.findByText("저장 상태: 저장됨");
  // 저장은 성공했지만 실측 오류 문구는 남아 있고, 미리보기는 낡은 것으로 표시된다
  expect(screen.getByRole("alert")).toHaveTextContent("실측 실패");
  expect(document.querySelector(".preview-canvas")).toHaveClass("stale");
  await userEvent.click(screen.getByRole("button", { name: "다시 그리기" }));
  await waitFor(() => expect(api.measure).toHaveBeenCalledTimes(3));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(await preview().findByText("둘")).toBeInTheDocument();
  expect(document.querySelector(".preview-canvas")).not.toHaveClass("stale");
});
