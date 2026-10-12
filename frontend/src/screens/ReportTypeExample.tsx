import { useEffect, useState } from "react";
import { Button } from "../ui/Button";
import { REPORT_TYPE_GUIDES, REPORT_TYPES, type ReportType } from "./reportPurpose";

// 보고 유형 예시 영역 (개정판 D3b-5, 계획 4.5). 예시 둘러보기는 유형 선택과 분리한다: "이전 예시", "다음 예시"는
// 이 영역 안의 보기만 바꾸고 저장하지 않는다(리뷰 U11). 그림과 크게 보기는 D3b-6이 더한다. 이 영역은 라이브 영역이
// 아니다(리뷰 U9)
export function ReportTypeExample({ selected }: { selected: ReportType | null }) {
  const [shown, setShown] = useState<ReportType | null>(selected);
  // 드롭다운에서 유형을 고르면 그 유형의 예시로 돌아온다
  useEffect(() => { setShown(selected); }, [selected]);
  const index = shown === null ? -1 : REPORT_TYPES.findIndex(([value]) => value === shown);
  const move = (step: number) => {
    const next = (index + step + REPORT_TYPES.length) % REPORT_TYPES.length;
    setShown(REPORT_TYPES[next][0]);
  };
  const label = index >= 0 ? REPORT_TYPES[index][1] : "";
  return (
    <section className="type-example" aria-label="보고 유형 예시">
      {shown === null ? (
        <p className="hint">유형을 고르면 예시가 보입니다.</p>
      ) : (
        <>
          <p><strong>{label}</strong> <span className="hint">(예시, 합성 자료)</span></p>
          <p className="hint">{REPORT_TYPE_GUIDES[shown].summary}</p>
        </>
      )}
      <div className="actions">
        <Button onClick={() => move(-1)}>이전 예시</Button>
        <Button onClick={() => move(1)}>다음 예시</Button>
      </div>
    </section>
  );
}
