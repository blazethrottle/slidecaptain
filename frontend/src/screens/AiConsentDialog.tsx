import { useEffect, useRef, useState } from "react";
import { api, type AppStatus } from "../api/client";

type StatusInfo = { provider: AppStatus["provider"]; model: string | null } | "loading" | "error";

function providerLabel(status: StatusInfo): string {
  if (status === "loading") return "확인 중...";
  if (status === "error") return "확인 실패";
  const providerName = status.provider === "subscription" ? "Claude 구독" : "미연결";
  return status.model ? `${providerName} (${status.model})` : providerName;
}

// AI 전송 고지 대화 상자 (계획서 B3, 가정 5, 6). ProjectView가 첫 AI 호출 전에 띄우고, 확인이나
// 취소의 결과를 콜백으로 돌려준다. 화면 전체를 덮는 오버레이라 뒤 화면의 클릭을 막는다.
export function AiConsentDialog({ onConfirm, onCancel }: {
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [status, setStatus] = useState<StatusInfo>("loading");
  const confirmRef = useRef<HTMLButtonElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    return () => {
      previouslyFocused.current?.focus();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.getStatus()
      .then((s) => { if (!cancelled) setStatus({ provider: s.provider, model: s.model ?? null }); })
      .catch(() => { if (!cancelled) setStatus("error"); });
    return () => { cancelled = true; };
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onCancel();
  };

  return (
    <div className="ai-consent-overlay" onKeyDown={onKeyDown}>
      <div className="ai-consent-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-consent-title">
        <h2 id="ai-consent-title">AI 에게 자료를 보냅니다</h2>
        <p>
          구조안 생성, 장 생성과 다시 생성, 축약을 누르면 이 프로젝트의 입력 자료 원문(엑셀 추출본 포함),
          보고 정보, 지시사항, 기존 초안이 AI 제공자 <strong>{providerLabel(status)}</strong> 에게
          전송됩니다. 형식 오류로 자동 재시도하거나 분량 초과로 자동 축약할 때도 같은 범위가 다시
          전송됩니다.
        </p>
        <p>
          프로젝트 파일은 이 PC 의 프로젝트 폴더에만 저장되고, 이 앱은 문서 내용이나 사용 기록을
          다른 분석 서버로 보내지 않습니다.
        </p>
        <p>
          제공자가 전송된 내용을 보관하거나 학습에 쓰는지는 이 앱이 단정하지 않습니다. 제공자의
          정책을 확인해 주세요.
        </p>
        <p>이 확인은 지금 연 브라우저 탭에서만 유효하며, 탭을 닫고 다시 열면 다시 묻습니다.</p>
        <div className="actions">
          <button ref={confirmRef} onClick={onConfirm}>전송에 동의하고 계속</button>
          <button onClick={onCancel}>취소</button>
        </div>
      </div>
    </div>
  );
}
