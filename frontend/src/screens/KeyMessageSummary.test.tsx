// 구성 화면의 핵심 내용 요약 줄 (D3b-7). 빈 값 판정은 서버와 같은 공백 문자 집합이다 (β 묶음 리뷰 B8)
import { render, screen } from "@testing-library/react";
import { KeyMessageSummary } from "./KeyMessageSummary";

it("서버가 빈 값으로 보는 공백 문자뿐이면 핵심 내용이 없다고 보인다", () => {
  render(<KeyMessageSummary text={"\u001c\u0085"} />);
  expect(screen.getByText("보고 목적에 핵심 내용이 없습니다.")).toBeInTheDocument();
});

it("서버가 빈 값으로 보지 않는 문자는 핵심 내용으로 보인다", () => {
  const { container } = render(<KeyMessageSummary text={"﻿"} />);
  expect(screen.queryByText("보고 목적에 핵심 내용이 없습니다.")).toBeNull();
  expect(container.querySelector("#key-message-summary-text")).not.toBeNull();
});
