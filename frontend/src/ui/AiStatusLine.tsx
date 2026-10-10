import { useEffect, useState } from "react";
import { api, type AppStatus } from "../api/client";

/** 상태 응답을 한 줄 문구로 바꾼다 (계획서 2026-09-01 태스크 4, 파일럿 관찰 5). */
export function describeStatus(status: AppStatus): string {
  const { login } = status;
  if (login.logged_in === true) {
    const last = status.last_generation_at
      ? status.last_generation_at.slice(0, 16).replace("T", " ")
      : "아직 없음";
    return `AI 연결: 로그인됨 (${login.auth_method ?? "방식 미상"}, ${login.account ?? "계정 미상"}). `
      + `마지막 생성 성공: ${last}`;
  }
  if (login.logged_in === false) {
    return "AI 연결: 로그인되지 않았습니다. AI 연결 및 모델 화면에서 로그인해 주세요.";
  }
  const version = login.cli_version ? `, CLI ${login.cli_version}` : "";
  return `AI 연결: 확인하지 못했습니다 (${login.error ?? "원인 미상"}${version}).`;
}

function providerPrefix(s: AppStatus): string {
  return s.provider === "claude" || s.provider === "chatgpt"
    ? `${s.provider === "claude" ? "Claude" : "ChatGPT"} / ${s.model}` : "";
}

/** 프로젝트 화면 상단 머리의 짧은 연결 표시 (D3a-2, 제품 설계 3절 배치도의 "Claude, 회사 계정"). */
export function compactStatus(s: AppStatus): string {
  const login = s.login.logged_in === true ? "로그인됨" : s.login.logged_in === false ? "로그인 필요" : "확인하지 못함";
  const prefix = providerPrefix(s);
  return prefix ? `${prefix}, ${login}` : `AI 연결: ${login}`;
}

/** 현재 AI 연결 한 줄. AI 설정에서 선택을 바꾸면(slidecaptain:ai-selection) 다시 읽는다. */
export function AiStatusLine({ compact = false, className = "ai-status" }: { compact?: boolean; className?: string }) {
  const [line, setLine] = useState("AI 연결 상태를 확인하는 중...");
  useEffect(() => {
    let alive = true;
    // 상태 조회 실패는 화면을 막지 않는다 (오류 영역이 아니라 상태 줄에만 남긴다)
    const refresh = () => api.getStatus()
      .then((s) => { if (alive) setLine(compact ? compactStatus(s) : (providerPrefix(s) ? `${providerPrefix(s)}. ` : "") + describeStatus(s)); })
      .catch(() => { if (alive) setLine("AI 연결 상태를 불러오지 못했습니다."); });
    void refresh();
    window.addEventListener("slidecaptain:ai-selection", refresh);
    return () => { alive = false; window.removeEventListener("slidecaptain:ai-selection", refresh); };
  }, [compact]);
  return <p className={className} role={compact ? undefined : "status"}>{line}</p>;
}
