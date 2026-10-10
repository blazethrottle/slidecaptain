import type { ExportResult } from "../api/client";
import { Button } from "../ui/Button";
import { ExportHistoryPanel } from "./ExportHistoryPanel";
import { ExportQualitySummary } from "./ExportQualitySummary";

// 검토와 내보내기 단계 (개정판 D3a-2, 계획 4.1). 옛 내보내기 버튼, 품질 요약, 검수 이력 탭을 한 화면에 모은다.
// 자동 검사, 사람 검토, 파일 저장의 세 상태 구별과 제출본 자격 영역의 배치는 단계 상태(D3a-3)와 함께 다듬는다
export function ReviewScreen({
  projectName, hasSlides, exporting, exportDisabled, exportTitle, exportResult, historyRevision, onExport,
  onScreenReady, onDirtyChange,
}: {
  projectName: string;
  hasSlides: boolean;
  exporting: boolean;
  exportDisabled: boolean;  // 이탈 처리, 업로드, AI 생성, 대화 상자 같은 프로젝트 전체 잠금
  exportTitle?: string;
  exportResult: ExportResult | null;
  historyRevision: number;  // 새로 내보내면 이력 목록을 다시 읽는다
  onExport: () => void;
  onScreenReady?: (guard: (() => Promise<boolean>) | null) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  return (
    <div className="review-screen">
      <section aria-labelledby="review-export-heading">
        <h2 id="review-export-heading">초안 내보내기</h2>
        <p className="quality-notice">현재 산출물은 검수 전 초안입니다. 보고 흐름, 근거와 실제 PowerPoint 표시를 확인한 뒤 제출해 주세요.</p>
        <div className="actions">
          <Button variant="primary" onClick={onExport} disabled={!hasSlides || exporting || exportDisabled}
            title={exportTitle ?? "내용과 시각 품질을 검수하지 않은 초안으로 내보냅니다"}>초안 PPTX 내보내기</Button>
          {!hasSlides && <span className="hint">내보낼 장이 아직 없습니다.</span>}
        </div>
        {exportResult && <ExportQualitySummary result={exportResult} />}
      </section>
      <ExportHistoryPanel key={historyRevision} projectName={projectName} busy={exporting}
        onScreenReady={onScreenReady} onDirtyChange={onDirtyChange} />
    </div>
  );
}
