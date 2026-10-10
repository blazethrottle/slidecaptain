import type { ButtonHTMLAttributes } from "react";

// 버튼 계층 (개정판 D3a-1, 계획 4.6). 주 행동, 보조, 텍스트 행동, 위험 행동의 넷이다.
// 단계와 상태마다 주 행동은 정확히 1개다. 클래스가 없는 <button>은 보조로 그려지므로 보조는 이 컴포넌트를 쓰지 않아도 된다.
// 위험 행동: 제출본 게시, 스냅샷 복원, 보존본 복원, 후보 버리기, 자료 삭제.
// 장 내용 교체를 동반한 승인은 구성 단계의 주 행동이라 주 행동으로 두고, 위험은 승인 직전 확인 창이 알린다
// (위험 계층으로 바꾸면 그 상태의 주 행동이 0개가 된다).
export type ButtonVariant = "primary" | "secondary" | "text" | "danger";

export const BUTTON_CLASS: Record<ButtonVariant, string> = {
  primary: "btn-primary",
  secondary: "btn-secondary",
  text: "btn-text",
  danger: "btn-danger",
};

export function Button({ variant = "secondary", className, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  const classes = [BUTTON_CLASS[variant], className].filter(Boolean).join(" ");
  return <button {...rest} className={classes} data-variant={variant} />;
}
