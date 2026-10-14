// 단계 5A 묶음 C 태스크 C2/C3: GenerationUsage가 필수 필드가 되며 기존 결과 목 20곳이 깨진다.
// 이 헬퍼로 값 없음(모두 미확인) 상태의 사용량을 채워 넣는다.
import type { GenerationUsage } from "../api/client";

export function emptyUsage(): GenerationUsage {
  return {
    calls: 0,
    failed_calls: 0,
    unmeasured_calls: 0,
    models: [],
    input_tokens: null,
    output_tokens: null,
    cache_read_tokens: null,
    cache_creation_tokens: null,
    duration_ms: null,
    duration_api_ms: null,
    cost_usd: null,
    missing: [],
    records: [],
  };
}

// 사용량 표시는 모두 접힌 진단 상세 안에 있다 (개정판 D3a-4, 계획 4.3, R12). 기본 상태에서 보이지 않고,
// 진단 상세를 펼치면 보인다. 화면 시험과 헤드리스 확인이 같은 판정(보이는지)을 쓴다
export function expectUsageCollapsed(root: ParentNode = document.body): void {
  const usages = [...root.querySelectorAll<HTMLElement>(".usage")];
  expect(usages.length).toBeGreaterThan(0);
  for (const usage of usages) {
    const details = usage.closest<HTMLDetailsElement>("details.diagnostics");
    expect(details).not.toBeNull();
    expect(details!.open).toBe(false);
    expect(usage).not.toBeVisible();
  }
}
