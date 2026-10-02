import { useEffect, useRef, useState } from "react";
import { api, type AppStatus } from "../api/client";

type StatusInfo = AppStatus | "loading" | "error";

function providerLabel(status: StatusInfo): string {
  if (status === "loading") return "확인 중...";
  if (status === "error") return "확인 실패";
  const providerName = status.provider === "subscription" || status.provider === "claude" ? "Claude 구독"
    : status.provider === "chatgpt" ? "ChatGPT 구독" : "미연결";
  return status.model ? `${providerName} (${status.model})` : providerName;
}

// AI 전송 고지 대화 상자 (계획서 B3, 가정 5, 6). ProjectView가 첫 AI 호출 전에 띄우고, 확인이나
// 취소의 결과를 콜백으로 돌려준다. 화면 전체를 덮는 오버레이라 뒤 화면의 클릭을 막는다.
export function AiConsentDialog({ onConfirm, onCancel, statusSnapshot }: {
  onConfirm: () => void;
  onCancel: () => void;
  statusSnapshot?: AppStatus;
}) {
  const [status, setStatus] = useState<StatusInfo>(statusSnapshot ?? "loading");
  const confirmRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    // 호출 버튼이 busy로 잠기면서 이미 포커스를 잃었을 수도 있다. 살아 있는 아래쪽 모달을 함께 기억한다.
    const underlyingDialog = previouslyFocused.current?.closest<HTMLElement>('[role="dialog"]') ??
      Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]'))
        .filter(element => element !== dialogRef.current && !element.closest('[inert], [hidden], [aria-hidden="true"]')).at(-1);
    cancelRef.current?.focus();
    return () => {
      const previous = previouslyFocused.current;
      if (previous && previous !== document.body && previous.isConnected && !previous.closest("[inert]")) {
        previous.focus();
        if (document.activeElement === previous) return;
      }
      // 동의를 닫아도 생성 요청은 진행 중이다. 비활성 호출 버튼 대신 원래 작성창의 활성 입력으로 복귀한다.
      if (!underlyingDialog?.isConnected || underlyingDialog.closest('[inert], [hidden], [aria-hidden="true"]')) return;
      const controls = underlyingDialog.querySelectorAll<HTMLElement>(
        'input:not(:disabled), textarea:not(:disabled), select:not(:disabled), button:not(:disabled), summary',
      );
      for (const control of controls) {
        if (control.closest('[hidden], [aria-hidden="true"], [inert]') ||
            (control.closest('details:not([open])') && control.tagName !== "SUMMARY")) continue;
        control.focus();
        if (document.activeElement === control) break;
      }
    };
  }, []);

  useEffect(() => {
    if (statusSnapshot) return;
    let cancelled = false;
    api.getStatus()
      .then((s) => { if (!cancelled) setStatus(s); })
      .catch(() => { if (!cancelled) setStatus("error"); });
    return () => { cancelled = true; };
  }, [statusSnapshot]);

  const canConfirm = status !== "loading" && status !== "error"
    && status.provider !== "none" && status.login.logged_in === true;
  useEffect(() => { if (canConfirm) confirmRef.current?.focus(); }, [canConfirm]);

  // 포커스 트랩: role="dialog" aria-modal="true" 선언만으로는 Tab이 배경 요소로 새는 것을
  // 막지 못한다(B 묶음 최종 리뷰 major F-2). 대화 상자 안 포커스 가능 요소는 확인과 취소 두
  // 버튼뿐이라 라이브러리 없이 둘 사이만 순환시킨다.
  const onKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation();
    if (e.key === "Escape") { onCancel(); return; }
    if (e.key !== "Tab") return;
    if (!canConfirm) { e.preventDefault(); cancelRef.current?.focus(); return; }
    if (e.shiftKey) {
      if (document.activeElement === confirmRef.current) {
        e.preventDefault();
        cancelRef.current?.focus();
      }
    } else {
      if (document.activeElement === cancelRef.current) {
        e.preventDefault();
        confirmRef.current?.focus();
      }
    }
  };

  return (
    <div className="ai-consent-overlay" onKeyDown={onKeyDown}>
      <div ref={dialogRef} className="ai-consent-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-consent-title">
        <h2 id="ai-consent-title">AI 에게 자료를 보냅니다</h2>
        {status === "error" ? (
          // "AI 제공자 확인 실패에게 전송됩니다"처럼 조사가 어색하게 붙는 문장을 피한다(B 묶음
          // 최종 리뷰 nit F-5): 실패는 전송 대상 이름 자리에 끼워 넣지 않고 별도로 알린다
          <p>AI 제공자 정보를 확인하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.</p>
        ) : (
          <p>
            구조안 생성, 보고 계획 재작성, 장 생성과 다시 생성, 축약을 누르면 이 프로젝트의 입력 자료 원문(엑셀 추출본 포함),
            보고 정보, 지시사항, 기존 초안이 AI 제공자 <strong>{providerLabel(status)}</strong> 에게
            전송됩니다. 형식 오류로 자동 재시도하거나 분량 초과로 자동 축약할 때도 같은 범위가 다시
            전송됩니다.
          </p>
        )}
        <p>
          도식 초안 생성에는 선택한 주장, 그 주장에 연결된 등록된 근거 발췌, 보고 정보와 도식 제목,
          지시사항을 같은 AI 제공자에게 전송합니다. 형식 재시도에도 같은 범위를 보내며 이미지 파일은 전송하지 않습니다.
        </p>
        <p>
          프로젝트 파일은 이 PC 의 프로젝트 폴더에만 저장되고, 이 앱은 문서 내용이나 사용 기록을
          다른 분석 서버로 보내지 않습니다.
        </p>
        <p>
          제공자가 전송된 내용을 보관하거나 학습에 쓰는지는 이 앱이 단정하지 않습니다. 제공자의
          정책을 확인해 주세요.
        </p>
        <p>이 확인은 지금 연 브라우저 탭의 현재 서비스와 모델에만 유효합니다. 연결 설정을 바꾸거나 탭을 다시 열면 다시 묻습니다.</p>
        <div className="actions">
          <button ref={confirmRef} disabled={!canConfirm} onClick={onConfirm}>전송에 동의하고 계속</button>
          <button ref={cancelRef} onClick={onCancel}>취소</button>
        </div>
      </div>
    </div>
  );
}
