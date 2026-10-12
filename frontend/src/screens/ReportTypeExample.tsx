import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "../ui/Button";
import { ExampleArt, EXAMPLE_PAGES } from "./ExampleArt";
import { REPORT_TYPES, type ReportType } from "./reportPurpose";

// 보고 유형 예시 영역 (개정판 D3b-5, D3b-6, 계획 4.5와 4.6). 예시 둘러보기는 유형 선택과 분리한다: "이전 예시", "다음 예시"는
// 이 영역 안의 보기만 바꾸고 저장하지 않는다(리뷰 U11). 이 영역은 라이브 영역이 아니다(리뷰 U9)
export function ReportTypeExample({ selected }: { selected: ReportType | null }) {
  const [shown, setShown] = useState<ReportType | null>(selected);
  const [enlarged, setEnlarged] = useState(false);
  const enlargeRef = useRef<HTMLButtonElement>(null);
  // 드롭다운에서 유형을 고르면 그 유형의 예시로 돌아온다
  useEffect(() => { setShown(selected); }, [selected]);
  const index = shown === null ? -1 : REPORT_TYPES.findIndex(([value]) => value === shown);
  const move = (step: number) => {
    const next = (index + step + REPORT_TYPES.length) % REPORT_TYPES.length;
    setShown(REPORT_TYPES[next][0]);
  };
  const label = index >= 0 ? REPORT_TYPES[index][1] : "";
  const close = () => {
    setEnlarged(false);
    enlargeRef.current?.focus();  // 닫으면 크게 보기 버튼으로 초점이 돌아간다 (리뷰 U8)
  };
  return (
    <section className="type-example" aria-label="보고 유형 예시">
      {shown === null ? (
        <p className="hint">유형을 고르면 예시가 보입니다.</p>
      ) : (
        <>
          <p className="type-example-caption"><strong>{label}</strong> <span className="hint">{EXAMPLE_PAGES[shown].page}</span></p>
          <ExampleArt type={shown} className="example-art" />
          <p className="hint">유형의 특징을 보여 주는 대표 페이지입니다. 모든 수치와 문구는 합성 예시이며 실제 내용은 입력한 자료로 작성합니다.</p>
        </>
      )}
      <div className="actions">
        <Button onClick={() => move(-1)}>이전 예시</Button>
        <Button onClick={() => move(1)}>다음 예시</Button>
        {shown !== null && <button type="button" ref={enlargeRef} onClick={() => setEnlarged(true)}>크게 보기</button>}
      </div>
      {enlarged && shown !== null && <EnlargedExample type={shown} label={label} onClose={close} />}
    </section>
  );
}

// 크게 보기 대화 상자 (리뷰 U8, U9). 열면 닫기 버튼으로 초점이 간다. 좁은 창에서는 가로 폭을 다 쓰고 그림은 원래 비율에
// 가깝게 보이며 필요하면 가로로 스크롤한다
function EnlargedExample({ type, label, onClose }: { type: ReportType; label: string; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeRef.current?.focus(); }, []);
  // 초점 가능한 요소가 닫기 버튼 하나뿐이라 Tab이 대화 상자 밖으로 나가지 않게 붙잡는다
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    if (e.key === "Tab") { e.preventDefault(); closeRef.current?.focus(); }
  };
  return (
    <div className="example-overlay" onKeyDown={onKeyDown}>
      <div className="example-dialog" role="dialog" aria-modal="true" aria-labelledby="example-dialog-title">
        <h2 id="example-dialog-title">{label} 예시: {EXAMPLE_PAGES[type].page}</h2>
        <div className="example-dialog-art"><ExampleArt type={type} className="example-art-large" /></div>
        <div className="actions">
          <button type="button" ref={closeRef} onClick={onClose} className="example-close">닫기</button>
        </div>
      </div>
    </div>
  );
}
