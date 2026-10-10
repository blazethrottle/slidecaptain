// 버튼 계층 컴포넌트의 계약 시험 (D3a-1, 계획 4.6)
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button, type ButtonVariant } from "./Button";

it.each([
  ["primary", "btn-primary"],
  ["secondary", "btn-secondary"],
  ["text", "btn-text"],
  ["danger", "btn-danger"],
] as [ButtonVariant, string][])("%s 계층은 button 역할과 내용 문구의 접근 이름, %s 클래스를 갖는다", (variant, cls) => {
  render(<Button variant={variant}>보고 정보 저장</Button>);
  const button = screen.getByRole("button", { name: "보고 정보 저장" });
  expect(button).toHaveClass(cls);
  expect(button).toHaveAttribute("data-variant", variant);
});

it("계층을 정하지 않으면 보조다", () => {
  render(<Button>닫기</Button>);
  expect(screen.getByRole("button", { name: "닫기" })).toHaveClass("btn-secondary");
});

it("aria-label이 있으면 그것이 접근 이름이고, 추가 클래스와 비활성, 누름을 그대로 넘긴다", async () => {
  const onClick = vi.fn();
  const { rerender } = render(
    <Button variant="danger" aria-label="1번 장 후보 버리기" className="extra" onClick={onClick}>후보 버리기</Button>);
  const button = screen.getByRole("button", { name: "1번 장 후보 버리기" });
  expect(button).toHaveClass("btn-danger", "extra");
  await userEvent.click(button);
  expect(onClick).toHaveBeenCalledTimes(1);
  rerender(<Button variant="danger" aria-label="1번 장 후보 버리기" disabled onClick={onClick}>후보 버리기</Button>);
  expect(screen.getByRole("button", { name: "1번 장 후보 버리기" })).toBeDisabled();
});

it("type을 정하지 않으면 button이라 폼 안에서 눌러도 폼을 제출하지 않는다 (D3a-1 리뷰 R20)", async () => {
  const onSubmit = vi.fn((e: { preventDefault: () => void }) => e.preventDefault());
  render(<form onSubmit={onSubmit}><Button variant="primary">저장</Button><Button type="submit">제출</Button></form>);
  await userEvent.click(screen.getByRole("button", { name: "저장" }));
  expect(onSubmit).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "제출" }));
  expect(onSubmit).toHaveBeenCalledTimes(1);
});
