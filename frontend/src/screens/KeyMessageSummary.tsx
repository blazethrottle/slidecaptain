import { useLayoutEffect, useRef, useState } from "react";

// 구성 화면 맨 위의 핵심 내용 요약 줄 (개정판 D3b-7, 계획 4.7, 리뷰 U17). 보고 목적에서 입력한 핵심 내용을 읽기 전용으로
// 보이고 같은 내용을 다시 입력하게 하지 않는다. 세 줄 뒤 접고 "더 보기"로 펼친다
export function KeyMessageSummary({ text, onEdit, editDisabled = false }: {
  text: string; onEdit?: () => void; editDisabled?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [long, setLong] = useState(false);
  const ref = useRef<HTMLParagraphElement>(null);
  const blank = !text.trim();
  // 접은 상태에서 넘치는지 잰다. 재지 못하는 환경(시험)은 줄 수로 판단한다
  useLayoutEffect(() => {
    const el = ref.current;
    setLong(text.split("\n").length > 3 || (!!el && el.scrollHeight > el.clientHeight + 1));
  }, [text]);
  return (
    <section className="key-message-summary" aria-labelledby="key-message-summary-title">
      <h2 id="key-message-summary-title">전달할 핵심 내용</h2>
      {blank ? <p className="hint">보고 목적에 핵심 내용이 없습니다.</p> : (
        <p ref={ref} id="key-message-summary-text" className={expanded ? "key-message-text" : "key-message-text clamped"}>{text}</p>
      )}
      <div className="actions">
        {!blank && long && (
          <button type="button" aria-expanded={expanded} aria-controls="key-message-summary-text"
            onClick={() => setExpanded((v) => !v)}>{expanded ? "접기" : "더 보기"}</button>
        )}
        {onEdit && <button type="button" onClick={onEdit} disabled={editDisabled}>보고 목적에서 고치기</button>}
      </div>
    </section>
  );
}
