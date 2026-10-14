import { useEffect, useRef, useState } from "react";

// 보존하지 못한 변경을 사용자가 직접 복사해 보관하게 하는 상자 (D2a-2).
// 도식 작성창의 DiagramDraftBackup과 같은 복사 방식이다. 자동 불러오기는 하지 않는다.
export function UnsavedChangeBackup({ text, label }: { text: string; label: string }) {
  const [notice, setNotice] = useState("");
  const currentText = useRef(text);
  currentText.current = text;
  const attempt = useRef(0);
  useEffect(() => { setNotice(""); }, [text]);
  useEffect(() => () => { attempt.current++; }, []);

  const copy = async () => {
    const request = ++attempt.current;
    setNotice("");
    try {
      await navigator.clipboard.writeText(text);
      if (request === attempt.current && text === currentText.current) setNotice("변경 내용을 복사했습니다.");
    } catch {
      if (request === attempt.current && text === currentText.current) {
        setNotice("복사하지 못했습니다. 아래 보관용 내용을 선택해 직접 복사해 주세요.");
      }
    }
  };

  return <details className="unsaved-change-backup" open>
    <summary>{label}</summary>
    <div className="field"><label>보관용 변경 내용<textarea readOnly rows={8} value={text}
      onFocus={event => event.currentTarget.select()} /></label></div>
    <button onClick={() => void copy()}>변경 내용 복사</button>
    {notice && <p role="status">{notice}</p>}
  </details>;
}
