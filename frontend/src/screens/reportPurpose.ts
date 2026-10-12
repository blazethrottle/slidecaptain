// 보고 목적 화면의 표와 판정 (개정판 D3b-5, 계획 4.5). 칸 표와 길이 상한은 서버(models/report_purpose.py)와 같아야
// 한다. 시험이 서버가 쓰는 고정 파일(backend/tests/fixtures/report-purpose-fields.json)과 비교한다
import type { Deck } from "../api/client";

type Meta = Deck["meta"];
export type ReportType = Meta["report_type"];
export type DesiredOutcome = NonNullable<Meta["desired_outcome"]>;

// 보고 유형 목록과 화면 이름 (D3a-2, D3b-1 리뷰 R3)
export const REPORT_TYPES = [
  ["weekly", "주간 업무 보고"],
  ["business", "일반 업무 보고"],
  ["monthly", "월간 보고"],
  ["data", "데이터 설명 보고"],
  ["research", "리서치 결과 보고"],
  ["project", "프로젝트 보고"],
  ["results", "결과 보고"],
  ["approval", "승인요청"],
  ["strategy", "전략기획"],
  ["ir", "IR Pitch Deck"],
] as const satisfies ReadonlyArray<readonly [Deck["meta"]["report_type"], string]>;
// 빠진 유형이 있으면 타입 검사가 실패한다. 없는 옵션의 값은 브라우저가 첫 옵션으로 보여 사용자가 보는 유형과
// 저장된 유형이 달라진다 (D3b-1 리뷰 R3)
type MissingReportType = Exclude<Deck["meta"]["report_type"], (typeof REPORT_TYPES)[number][0]>;
const reportTypesComplete: [MissingReportType] extends [never] ? true : never = true;
void reportTypesComplete;

export const KEY_MESSAGE_MAX = 8_000;
export const OUTCOME_OTHER_MAX = 8_000;
export const DETAIL_MAX = 1_000;

// 유형별 추가 입력 칸. 저장 키는 "유형.칸"이다
export const REPORT_DETAIL_FIELDS: Record<ReportType, ReadonlyArray<readonly [string, string]>> = {
  weekly: [["period", "보고 기간"], ["baseline", "계획 또는 이전 보고서"]],
  business: [["target_work", "대상 업무"], ["share_purpose", "공유 목적"]],
  monthly: [["month", "대상 월"], ["comparison_basis", "목표 또는 비교 기준"]],
  data: [["metrics", "주요 지표"], ["scope", "기간과 대상"]],
  research: [["question", "조사 질문"], ["scope", "조사 범위"]],
  project: [["project", "프로젝트"], ["reference_date", "기준일"], ["milestones", "주요 마일스톤"]],
  results: [["activity_scope", "활동 범위"], ["goal_criteria", "목표와 평가 기준"]],
  approval: [["decision_question", "결정할 질문"], ["alternatives", "대안"]],
  strategy: [["goal", "목표"], ["review_period", "검토 기간"]],
  ir: [["investment_stage", "투자 단계"], ["ask_and_use", "투자 요청과 사용 계획"]],
};

// 유형 설명과 추천 구성 (시안의 유형 표, 제품 설계 5절 B). 구성은 순서 목록으로 보인다
export const REPORT_TYPE_GUIDES: Record<ReportType, { summary: string; composition: string[] }> = {
  weekly: { summary: "실적과 다음 주 계획을 정리합니다.",
    composition: ["이번 주 요약", "실적과 계획 차이", "이슈와 지원 요청", "다음 주 계획"] },
  business: { summary: "현재 업무와 후속 행동을 정리합니다.",
    composition: ["업무 현황", "수행 내용", "주요 이슈", "후속 행동"] },
  monthly: { summary: "목표 대비 변화와 원인을 정리합니다.",
    composition: ["월간 요약", "목표 대비 실적", "전월 변화", "다음 달 계획"] },
  data: { summary: "지표의 의미와 해석을 설명합니다.",
    composition: ["질문", "지표와 범위", "관측 결과", "해석과 한계"] },
  research: { summary: "발견과 근거, 시사점을 정리합니다.",
    composition: ["조사 질문", "방법과 범위", "발견", "시사점과 한계"] },
  project: { summary: "진척과 필요한 결정을 정리합니다.",
    composition: ["목표와 범위", "진척과 마일스톤", "위험과 결정", "다음 단계"] },
  results: { summary: "목표와 성과, 교훈을 정리합니다.",
    composition: ["목표와 평가 기준", "수행과 산출", "달성 여부", "교훈과 후속"] },
  approval: { summary: "대안과 추천 근거로 승인을 요청합니다.",
    composition: ["요청", "배경", "대안과 추천", "실행과 위험"] },
  strategy: { summary: "방향과 실행 순서를 제시합니다.",
    composition: ["핵심 결론", "현황과 변화", "방향과 근거", "실행 순서"] },
  ir: { summary: "사업의 성장 가능성과 투자 제안을 설명합니다.",
    composition: ["문제", "해결책과 제품", "시장", "사업 모델", "성과", "성장 전략", "팀", "투자 요청, 자금 사용과 마일스톤"] },
};

// 원하는 결과 (제품 설계 6절). 보고 유형과 다른 축이다
export const OUTCOMES: ReadonlyArray<readonly [DesiredOutcome, string]> = [
  ["facts", "사실 및 데이터 중심 보고서"],
  ["business_plan", "사업 기획안"],
  ["persuasion", "투자자 및 의사결정자 설득"],
  ["other", "기타 (직접 입력)"],
];

// 서버(Python str.strip, str.isspace)와 같은 공백 문자 집합. JavaScript trim()은 U+FEFF를 공백으로 보고 U+001C~U+001F와
// U+0085는 보지 않아, 빈 값 판정이 서버와 갈렸다 (D3b-5 리뷰 R5)
const PY_SPACE = "\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const BLANK = new RegExp(`^[${PY_SPACE}]*$`);
const EDGE_SPACE = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, "g");
export const isBlank = (value: string | null | undefined) => !value || BLANK.test(value);
const pyStrip = (value: string) => value.replace(EDGE_SPACE, "");

// 유형이 확인됐는가. 서버의 진행 판정과 같다(확인 표시가 있거나 기본 유형이 아님)
export const typeConfirmed = (meta: Meta) => !!meta.report_type_confirmed || meta.report_type !== "research";

// 지시문이 읽는 보고 목적 값. 서버의 purpose_prompt_values와 같은 칸을 같은 규칙(앞뒤 공백 정리)으로 고른다.
// 이 값이 바뀌면 저장된 구성 계획이 낡는다 (계획 4.5 미리 알림, α 묶음 리뷰 A5, A6)
export function purposePromptValues(meta: Meta): Record<string, string> {
  const values: Record<string, string> = {};
  if (!isBlank(meta.key_message)) values.key_message = pyStrip(meta.key_message!);
  if (meta.desired_outcome) {
    values.desired_outcome = meta.desired_outcome;
    if (meta.desired_outcome === "other" && !isBlank(meta.desired_outcome_other)) {
      values.desired_outcome_other = pyStrip(meta.desired_outcome_other!);
    }
  }
  for (const [name] of REPORT_DETAIL_FIELDS[meta.report_type]) {
    const value = meta.report_details?.[`${meta.report_type}.${name}`];
    if (!isBlank(value)) values[`detail.${name}`] = pyStrip(value!);
  }
  return values;
}

// 저장된 구성 계획을 낡게 하는 메타 값. 서버 story_fingerprint가 담는 메타 칸(제목, 피보고자, 보고 유형)과 지시문이 읽는
// 보고 목적 값이다. 이 값이 바뀌면 미리 알린다 (D3b-5 리뷰 R1, R2)
export function planInputValues(meta: Meta): string {
  return JSON.stringify([meta.title, meta.audience ?? "", meta.report_type, purposePromptValues(meta)]);
}

// 생성에 쓰지 않는 입력(숨은 입력): 다른 유형의 추가 입력과, 기타가 아닐 때의 기타 설명
export function hiddenInputs(meta: Meta): { details: string[]; other: boolean } {
  const prefix = `${meta.report_type}.`;
  const details = Object.entries(meta.report_details ?? {})
    .filter(([key, value]) => !key.startsWith(prefix) && !isBlank(value)).map(([key]) => key);
  return { details, other: meta.desired_outcome !== "other" && !isBlank(meta.desired_outcome_other) };
}

// 저장할 값이 같은가. 빈 문자열과 없는 칸, 공백만 있는 추가 입력과 없는 칸을 같게 본다(서버가 빈 값을 빼고
// 기본값을 직렬화하지 않아 다시 읽은 덱과 보낸 값의 모양이 다르다, D3b-1 리뷰 R13)
export function purposeMetaEqual(a: Meta, b: Meta): boolean {
  const details = (m: Meta) => JSON.stringify(Object.entries(m.report_details ?? {})
    .filter(([, value]) => !isBlank(value)).sort(([x], [y]) => x.localeCompare(y)));
  return a.title === b.title && a.report_type === b.report_type
    && (a.presenter ?? "") === (b.presenter ?? "") && (a.audience ?? "") === (b.audience ?? "")
    && !!a.report_type_confirmed === !!b.report_type_confirmed
    && (a.key_message ?? "") === (b.key_message ?? "")
    && (a.desired_outcome ?? null) === (b.desired_outcome ?? null)
    && (a.desired_outcome_other ?? "") === (b.desired_outcome_other ?? "")
    && details(a) === details(b);
}
