import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Button } from "../ui/Button";
import { ExampleArt, EXAMPLE_PAGES } from "./ExampleArt";
import { REPORT_TYPE_GUIDES, REPORT_TYPES, type ReportType } from "./reportPurpose";

// 보고 유형 예시 영역 (개정판 D3b-5, D3b-6, 계획 4.5와 4.6). 예시 둘러보기는 유형 선택과 분리한다: "이전 예시", "다음 예시"는
// 이 영역 안의 보기만 바꾸고 저장하지 않는다(리뷰 U11). 이 영역은 라이브 영역이 아니다(리뷰 U9)
// closed: 화면이 충돌로 멈추면 크게 보기를 닫는다. 열린 채면 앱 화면이 비활성이라 충돌 안내가 대화 상자 뒤에 가려졌다
// (β 묶음 리뷰 B7)
export function ReportTypeExample({ selected, closed = false }: { selected: ReportType | null; closed?: boolean }) {
  const [shown, setShown] = useState<ReportType | null>(selected);
  const [enlarged, setEnlarged] = useState(false);
  useEffect(() => { if (closed) setEnlarged(false); }, [closed]);
  const enlargeRef = useRef<HTMLButtonElement>(null);
  // 드롭다운에서 유형을 고르면 그 유형의 예시로 돌아온다
  useEffect(() => { setShown(selected); }, [selected]);
  const index = shown === null ? -1 : REPORT_TYPES.findIndex(([value]) => value === shown);
  const move = (step: number) => {
    // 아직 아무 예시도 보이지 않으면 "다음"은 처음, "이전"은 마지막 유형이다 (D3b-5 리뷰 R12)
    const from = index < 0 ? (step > 0 ? -1 : 0) : index;
    const next = (from + step + REPORT_TYPES.length) % REPORT_TYPES.length;
    setShown(REPORT_TYPES[next][0]);
  };
  const label = index >= 0 ? REPORT_TYPES[index][1] : "";
  // 닫으면 크게 보기 버튼으로 초점이 돌아간다 (리뷰 U8). 앱 화면의 비활성(inert)을 푼 뒤에 옮겨야 초점이 들어간다
  const close = () => setEnlarged(false);
  return (
    <section className="type-example" aria-label="보고 유형 예시">
      {shown === null ? (
        <p className="hint">유형을 고르면 예시가 보입니다.</p>
      ) : (
        <>
          <p><strong>{label} 예시: {EXAMPLE_PAGES[shown].page}</strong></p>
          {/* 고른 유형과 다른 유형을 둘러볼 때는 그 유형의 설명을 함께 보인다(드롭다운 아래 설명은 고른 유형의 것이다) */}
          {shown !== selected && <p className="hint">{REPORT_TYPE_GUIDES[shown].summary}</p>}
          <ExampleArt type={shown} className="example-art" />
          <p className="hint">유형의 특징을 보여 주는 대표 페이지입니다. 모든 수치와 문구는 합성 예시입니다. 실제 보고서는 입력한 자료로 만듭니다.</p>
        </>
      )}
      <div className="actions">
        <Button onClick={() => move(-1)}>이전 예시</Button>
        <Button onClick={() => move(1)}>다음 예시</Button>
        {shown !== null && <button type="button" ref={enlargeRef} onClick={() => setEnlarged(true)}>크게 보기</button>}
      </div>
      {enlarged && shown !== null && <EnlargedExample type={shown} label={label} onClose={close} returnFocus={enlargeRef} />}
    </section>
  );
}

// 크게 보기 대화 상자 (리뷰 U8, U9, D3b-6 리뷰 R2~R5). 문서 맨 위층(포털)에 그리고, 열려 있는 동안 앱 화면을 비활성(inert)으로
// 두고 스크롤을 잠근다. 키는 창 전체에서 받아 초점이 어디 있든 Esc로 닫고 Tab을 가둔다(마우스로 제목을 눌러 초점이 빠져도
// 같다). Esc는 다른 창(AI 설정 드로어)의 처리기로 넘기지 않는다. 닫기 버튼은 제목 줄에 두어 좁은 창에서도 첫 화면에 보인다.
// 좁은 창에서 가로로 넘치는 그림 영역은 초점을 받아 화살표 키로 스크롤할 수 있다
function EnlargedExample({ type, label, onClose, returnFocus }: {
  type: ReportType; label: string; onClose: () => void; returnFocus: RefObject<HTMLButtonElement | null>;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const artRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    closeRef.current?.focus({ preventScroll: true });
    if (dialogRef.current) dialogRef.current.scrollTop = 0;
    const root = document.getElementById("root");
    root?.setAttribute("inert", "");
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      e.preventDefault();
      const stops: HTMLElement[] = [];
      if (artRef.current) stops.push(artRef.current);
      if (closeRef.current) stops.push(closeRef.current);
      const at = stops.indexOf(document.activeElement as HTMLElement);
      const next = at < 0 ? stops.length - 1 : (at + (e.shiftKey ? -1 : 1) + stops.length) % stops.length;
      stops[next].focus();
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      root?.removeAttribute("inert");
      document.body.style.overflow = overflow;
      returnFocus.current?.focus();
    };
  }, [returnFocus]);
  // 좁은 창에서 가로로 넘치는 그림을 화살표, Home, End로 옮긴다 (D3b-6 리뷰 R5)
  const scrollByKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const box = e.currentTarget;
    const step = { ArrowLeft: -40, ArrowRight: 40, Home: -box.scrollWidth, End: box.scrollWidth }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    box.scrollLeft += step;
  };
  // 버튼이 아닌 곳을 눌러도 초점이 대화 상자 밖(문서 본문)으로 빠지지 않게 한다
  const keepFocus = (e: MouseEvent) => {
    if (!(e.target as HTMLElement).closest("button, [tabindex]")) e.preventDefault();
  };
  return createPortal(
    <div className="example-overlay" onMouseDown={keepFocus}>
      <div ref={dialogRef} className="example-dialog" role="dialog" aria-modal="true" aria-labelledby="example-dialog-title">
        <div className="example-dialog-head">
          <h2 id="example-dialog-title">{label} 예시: {EXAMPLE_PAGES[type].page}</h2>
          <button type="button" ref={closeRef} onClick={onClose} className="example-close">닫기</button>
        </div>
        <div ref={artRef} className="example-dialog-art" tabIndex={0} role="group" aria-label="확대한 예시 그림"
          onKeyDown={scrollByKey}>
          <ExampleArt type={type} className="example-art-large" />
        </div>
      </div>
    </div>,
    document.body,
  );
}
