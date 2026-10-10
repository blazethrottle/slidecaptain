import type { ExportResult } from "../api/client";
import { Button } from "../ui/Button";
import { StatusIndicator, type StatusKind } from "../ui/StatusIndicator";
import { READY_LIMITATIONS, reasonText, type ReviewPart, type StageProgress } from "./stageStatus";
import { ExportHistoryPanel } from "./ExportHistoryPanel";
import { ExportQualitySummary } from "./ExportQualitySummary";

// 검토와 내보내기 단계 (개정판 D3a-2, 계획 4.1). 옛 내보내기 버튼, 품질 요약, 검수 이력 탭을 한 화면에 모은다.
// 자동 검사, 사람 검토, 파일 저장의 세 상태는 한 상태로 합치지 않고 따로 보인다(D3a-3, 진행 API의 검토 단계 부분).
// 제출본 자격(PowerPoint 렌더, 서명된 독립 검수, 제출본 게시)은 내보낸 파일 하나를 골라야 하므로 내보내기 이력 상세의
// 검수 기록 아래 자기 영역("제출본 검수와 게시")에 둔다

const PART_LABELS: Record<ReviewPart["name"], string> = {
  auto_checks: "자동 검사(내보낸 파일 기준)",
  human_review: "사람 검토",
  file: "파일 저장",
};

function partStatus(part: ReviewPart): { kind: StatusKind; detail?: string } {
  // 시작 전에도 서버 사유(예: 아직 내보낸 파일이 없음)를 설명으로 붙인다 (D3a-3 리뷰 R15)
  if (part.state === "not_started") return { kind: "not_started", detail: part.reasons?.[0] ? reasonText(part.reasons[0]) : undefined };
  if (part.state === "ready") return { kind: "ready" };
  const shown = (part.reasons ?? []).filter((r) => !READY_LIMITATIONS.has(r));
  return { kind: "needs_review", detail: shown.length > 0 ? reasonText(shown[0]) : undefined };
}
export function ReviewScreen({
  projectName, hasSlides, exporting, exportDisabled, exportTitle, exportResult, historyRevision, onExport,
  onScreenReady, onDirtyChange, review, progressFailed = false,
}: {
  review?: StageProgress;  // 진행 API의 검토 단계. 세 부분의 상태와 사유를 담는다
  progressFailed?: boolean;
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
  const parts = review?.parts ?? [];
  // 조회가 실패하면 지난 응답의 한계 안내를 보이지 않는다 (D3a-3 리뷰 R14)
  const limitations = progressFailed ? []
    : [...new Set(parts.flatMap((p) => p.reasons ?? []).filter((r) => READY_LIMITATIONS.has(r)))];
  return (
    <div className="review-screen">
      <section aria-labelledby="review-state-heading">
        <h2 id="review-state-heading">검토 상태</h2>
        {progressFailed ? <p><StatusIndicator kind="unknown" /> 검토 상태를 읽지 못했습니다.</p>
          : !review ? <p>검토 상태를 읽는 중입니다.</p>
          : <ul className="review-parts" aria-label="검토의 세 부분">
            {parts.map((part) => {
              const st = partStatus(part);
              return <li key={part.name}><span className="review-part-name">{PART_LABELS[part.name]}</span>{" "}
                <StatusIndicator kind={st.kind} detail={st.detail} /></li>;
            })}
          </ul>}
        {limitations.map((r) => <p key={r} className="hint">{reasonText(r)}</p>)}
      </section>
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
