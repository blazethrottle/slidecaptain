import type { ExportResult, QualityReport } from "../api/client";

const checkNames: Record<string, string> = {
  nonempty_output: "슬라이드 존재",
  chapter_coverage: "장 구성 반영",
  layout_capacity: "레이아웃 용량",
  numeric_expressions: "계산 문구 대조",
  narrative: "보고 흐름",
  evidence: "근거 타당성",
  representation: "표현 적절성",
  visual: "시각 품질",
  target_renderer: "실제 PowerPoint 표시",
};
const statusNames = { passed: "항목 통과", failed: "확인 필요", not_run: "미수행" };

export function ExportQualitySummary({ result }: { result: ExportResult }) {
  const { quality, quality_path, path } = result;
  return (
    <section className="export-quality" aria-label="내보낸 초안의 점검 결과">
      <p className="export-path" role="status">
        초안 내보내기 완료: {path} (PowerPoint에서 여세요)<br />
        사전 점검 기록: {quality_path}<br />
        파일 생성 성공은 내용과 시각 품질의 검수 통과를 뜻하지 않습니다.
      </p>
      <PublishedQualityChecks quality={quality} />
    </section>
  );
}

export function PublishedQualityChecks({ quality }: { quality: QualityReport }) {
  const numeric = quality.numeric_review;
  const check = quality.checks.find(item => item.name === "numeric_expressions");
  const unresolved = numeric?.items.filter(item => item.code !== "matched") ?? [];
  return (
    <>
      <p><strong>내보낸 초안: {quality.status === "needs_revision" ? "확인 필요" : "검수 전 초안"}</strong></p>
      {numeric ? <>
        <p>수치 포함 칸 {numeric.numeric_fields}개, 검사 {numeric.evaluated}개, 일치 {numeric.matched}개, 확인 필요 {numeric.unresolved}개</p>
        {numeric.reason && check && <p>{check.detail}</p>}
      </> : <p>이 기록에는 계산 문구 대조 결과가 없습니다.</p>}
      <details>
        <summary>점검 항목과 확인할 문구</summary>
        <div className="export-quality-table">
          <table>
            <thead><tr><th>항목</th><th>상태</th><th>검사</th><th>문제</th></tr></thead>
            <tbody>{quality.checks.map(item => <tr key={item.name}>
              <th scope="row">{checkNames[item.name] ?? item.name}</th>
              <td>{statusNames[item.status]}</td>
              <td>{item.evaluated}개</td><td>{item.failed}개</td>
            </tr>)}</tbody>
          </table>
        </div>
        {unresolved.length > 0 && <ul>{unresolved.map(item => <li key={`${item.chapter_id}:${item.path}`}>
          <p>{item.message}</p>
          <p className="numeric-review-text">{item.actual}</p>
        </li>)}</ul>}
      </details>
      <p>{quality.notice}</p>
    </>
  );
}
