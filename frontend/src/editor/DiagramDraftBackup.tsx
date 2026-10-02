import { useEffect, useRef, useState } from "react";

export function DiagramDraftBackup({ text }: { text: string }) {
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
      if (request === attempt.current && text === currentText.current) setNotice("작성 내용을 복사했습니다.");
    } catch {
      if (request === attempt.current && text === currentText.current) {
        setNotice("복사하지 못했습니다. 아래 보관용 내용을 선택해 직접 복사해 주세요.");
      }
    }
  };

  return <details className="diagram-draft-backup">
    <summary>작성 내용 보관</summary>
    <p>입력은 이 창이 열려 있는 동안 유지됩니다. 창을 닫거나 새로고침하기 전에 필요한 내용을 복사해 보관해 주세요.</p>
    <p>이 텍스트는 다시 작성할 때 참고하는 용도입니다. 자동 불러오기와 근거 연결 복구는 아직 지원하지 않습니다.</p>
    <div className="field"><label>보관용 작성 내용<textarea readOnly rows={8} value={text}
      onFocus={event => event.currentTarget.select()} /></label></div>
    <button onClick={() => void copy()}>작성 내용 복사</button>
    {notice && <p role="status">{notice}</p>}
  </details>;
}
