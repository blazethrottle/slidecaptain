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
