// AI 사용량 화면 표시 (단계 5A 묶음 C 태스크 C4, 가정 3과 7). 값이 없으면 숫자를 지어내지 않고
// "미확인"을 쓴다. formatUsage는 한 줄 문구를, sumUsage는 여러 GenerationUsage의 합계를 만든다.
import type { GenerationUsage } from "./client";

type CallUsageRecord = GenerationUsage["records"][number];
type CallPurpose = CallUsageRecord["purpose"];

// 합계 대상 수치 필드 (백엔드 _USAGE_NUMERIC_FIELDS와 같은 순서. 가정 3)
const NUMERIC_FIELDS = [
  "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
  "duration_ms", "duration_api_ms", "cost_usd",
] as const;

function countByPurpose(records: CallUsageRecord[], purpose: CallPurpose): number {
  return records.filter((r) => r.purpose === purpose).length;
}

function formatTokenCount(n: number): string {
  return n.toLocaleString("ko-KR");
}

// 소수 4자리까지 표기하되 뒤 0은 제거한다 (가정 7). 0은 값이므로 "$0"으로 별도 처리한다.
function formatCost(cost: number): string {
  if (cost === 0) return "$0";
  const fixed = cost.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  return `$${fixed}`;
}

/** AI 사용량 한 줄 문구 (가정 7). None 값은 그 항목만 "미확인"으로 쓴다. */
export function formatUsage(usage: GenerationUsage): string {
  const qualifiers: string[] = [];
  if (usage.failed_calls > 0) qualifiers.push(`실패 ${usage.failed_calls}회 포함`);
  const retryCount = countByPurpose(usage.records, "format_retry");
  if (retryCount > 0) qualifiers.push(`형식 재시도 ${retryCount}회 포함`);
  const condenseCount = countByPurpose(usage.records, "condense");
  if (condenseCount > 0) qualifiers.push(`축약 ${condenseCount}회 포함`);

  // 실제 모델이 있으면 앞에 붙인다(가정 7). 여러 모델이 섞이면 그대로 나열한다
  const modelPrefix = usage.models.length > 0 ? `${usage.models.join(", ")} 로 ` : "";
  const parts: string[] = [
    `${modelPrefix}호출 ${usage.calls}회${qualifiers.length > 0 ? `(${qualifiers.join(", ")})` : ""}`,
  ];

  if (usage.unmeasured_calls > 0) {
    parts.push(`측정되지 않은 호출 ${usage.unmeasured_calls}회 제외`);
  }

  // model_usage가 없어 usage dict로 폴백한 호출이 하나라도 있으면 "대략"을 붙인다 (가정 1, 7)
  const approx = usage.records.some((r) => r.usage?.token_source === "usage");
  if (usage.input_tokens == null || usage.output_tokens == null) {
    parts.push("토큰 미확인");
  } else {
    // F4 리뷰 반영: usage dict 폴백은 입력과 출력 토큰에 같은 불확실성을 준다(가정 1).
    // "대략"을 입력에만 붙이면 출력 토큰이 마치 정확한 값처럼 보인다.
    const approxPrefix = approx ? "대략 " : "";
    parts.push(`${approxPrefix}입력 ${formatTokenCount(usage.input_tokens)} 토큰`);
    parts.push(`${approxPrefix}출력 ${formatTokenCount(usage.output_tokens)} 토큰`);
    if (usage.cache_read_tokens) {
      parts.push(`캐시 읽기 ${formatTokenCount(usage.cache_read_tokens)} 토큰`);
    }
    if (usage.cache_creation_tokens) {
      parts.push(`캐시 생성 ${formatTokenCount(usage.cache_creation_tokens)} 토큰`);
    }
  }

  if (usage.duration_ms == null) {
    parts.push("처리 시간 미확인");
  } else {
    parts.push(`처리 ${(usage.duration_ms / 1000).toFixed(1)}초`);
  }

  if (usage.cost_usd == null) {
    parts.push("비용 미확인");
  } else {
    parts.push(`참고 비용 ${formatCost(usage.cost_usd)} (AI 도구가 계산한 값으로 실제 청구액이 아닙니다)`);
  }

  return `AI 사용량: ${parts.join(", ")}`;
}

/** 여러 작업의 GenerationUsage를 하나로 합친다 (가정 3의 None 전파 규칙, records 이어붙임). */
export function sumUsage(list: GenerationUsage[]): GenerationUsage {
  const records: CallUsageRecord[] = list.flatMap((u) => u.records);
  const measured = records
    .map((r) => r.usage)
    .filter((u): u is NonNullable<typeof u> => u !== null);
  const failedCalls = records.filter((r) => !r.ok).length;
  const unmeasuredCalls = records.length - measured.length;
  const models = Array.from(
    new Set(measured.map((u) => u.model).filter((m): m is string => Boolean(m))),
  );

  const missing: string[] = [];
  const sumField = (name: (typeof NUMERIC_FIELDS)[number]): number | null => {
    const values = measured.map((u) => u[name]);
    if (values.length === 0) return null;
    if (values.some((v) => v === null)) {
      missing.push(name);
      return null;
    }
    return (values as number[]).reduce((a, b) => a + b, 0);
  };

  return {
    calls: records.length,
    failed_calls: failedCalls,
    unmeasured_calls: unmeasuredCalls,
    models,
    input_tokens: sumField("input_tokens"),
    output_tokens: sumField("output_tokens"),
    cache_read_tokens: sumField("cache_read_tokens"),
    cache_creation_tokens: sumField("cache_creation_tokens"),
    duration_ms: sumField("duration_ms"),
    duration_api_ms: sumField("duration_api_ms"),
    cost_usd: sumField("cost_usd"),
    missing,
    records,
  };
}
