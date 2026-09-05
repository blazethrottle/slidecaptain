import type { GenerationUsage } from "./client";
import { emptyUsage } from "../test/usage";
import { formatUsage, sumUsage } from "./usage";

type CallUsage = NonNullable<GenerationUsage["records"][number]["usage"]>;

function callUsage(overrides: Partial<CallUsage> = {}): CallUsage {
  return {
    model: "claude-sonnet-4-5-20250929",
    input_tokens: 100,
    output_tokens: 50,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    duration_ms: 1000,
    duration_api_ms: 900,
    num_turns: 1,
    cost_usd: 0.001,
    stop_reason: null,
    terminal_reason: "completed",
    api_error_status: null,
    token_source: "model_usage",
    ...overrides,
  };
}

// 계획서 가정 7의 정본 예시(구조안 생성 1회 + 형식 재시도 1회): 이 문자열은 그대로 맞춰야 한다
function canonicalUsage(): GenerationUsage {
  return {
    ...emptyUsage(),
    calls: 2,
    models: [],
    input_tokens: 12345,
    output_tokens: 1234,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    duration_ms: 8200,
    duration_api_ms: 7900,
    cost_usd: 0.0123,
    records: [
      { purpose: "generate", ok: true, usage: callUsage({ model: null }) },
      { purpose: "format_retry", ok: true, usage: callUsage({ model: null }) },
    ],
  };
}

describe("formatUsage", () => {
  it("정본 예시 문자열을 그대로 만든다", () => {
    expect(formatUsage(canonicalUsage())).toBe(
      "AI 사용량: 호출 2회(형식 재시도 1회 포함), 입력 12,345 토큰, 출력 1,234 토큰, " +
      "처리 8.2초, 참고 비용 $0.0123 (AI 도구가 계산한 값으로 실제 청구액이 아닙니다)",
    );
  });

  it("토큰이 null이면 '토큰 미확인'을 쓴다", () => {
    const usage: GenerationUsage = {
      ...emptyUsage(), calls: 1,
      records: [{ purpose: "generate", ok: true, usage: callUsage({ input_tokens: null, output_tokens: null }) }],
    };
    expect(formatUsage(usage)).toContain("토큰 미확인");
    expect(formatUsage(usage)).not.toContain("입력");
  });

  it("비용이 null이면 '비용 미확인'을 쓴다", () => {
    const usage: GenerationUsage = {
      ...emptyUsage(), calls: 1, input_tokens: 10, output_tokens: 5, duration_ms: 100,
      records: [{ purpose: "generate", ok: true, usage: callUsage({ cost_usd: null }) }],
    };
    expect(formatUsage(usage)).toContain("비용 미확인");
    expect(formatUsage(usage)).not.toContain("참고 비용");
  });

  it("비용이 0이면 '$0'을 쓰고 값을 지어내지 않는다", () => {
    const usage: GenerationUsage = {
      ...emptyUsage(), calls: 1, input_tokens: 10, output_tokens: 5, duration_ms: 100, cost_usd: 0,
      records: [{ purpose: "generate", ok: true, usage: callUsage({ cost_usd: 0 }) }],
    };
    expect(formatUsage(usage)).toContain("참고 비용 $0 (");
  });

  it("캐시 토큰이 0이면 생략하고, 값이 있으면 표시한다", () => {
    const withoutCache = canonicalUsage();
    expect(formatUsage(withoutCache)).not.toContain("캐시");

    const withCache: GenerationUsage = {
      ...canonicalUsage(), cache_read_tokens: 500,
      records: [
        { purpose: "generate", ok: true, usage: callUsage({ model: null, cache_read_tokens: 500 }) },
      ],
    };
    expect(formatUsage(withCache)).toContain("캐시 읽기 500 토큰");
  });

  it("실패, 재시도, 축약 포함 문구를 붙인다", () => {
    const usage: GenerationUsage = {
      ...emptyUsage(), calls: 3, failed_calls: 1, input_tokens: 10, output_tokens: 5, duration_ms: 100, cost_usd: 0.1,
      records: [
        { purpose: "generate", ok: true, usage: callUsage() },
        { purpose: "condense", ok: false, usage: callUsage() },
        { purpose: "format_retry", ok: true, usage: callUsage() },
      ],
    };
    const text = formatUsage(usage);
    expect(text).toContain("실패 1회 포함");
    expect(text).toContain("형식 재시도 1회 포함");
    expect(text).toContain("축약 1회 포함");
  });

  it("measured되지 않은 호출이 있으면 '측정되지 않은 호출 N회 제외'를 붙인다", () => {
    const usage: GenerationUsage = {
      ...emptyUsage(), calls: 2, failed_calls: 1, unmeasured_calls: 1,
      input_tokens: 10, output_tokens: 5, duration_ms: 100, cost_usd: 0.1,
      records: [
        { purpose: "generate", ok: true, usage: callUsage() },
        { purpose: "condense", ok: false, usage: null },
      ],
    };
    expect(formatUsage(usage)).toContain("측정되지 않은 호출 1회 제외");
  });

  it("token_source가 usage인 레코드가 있으면 입력과 출력 토큰 앞에 모두 '대략'을 붙인다", () => {
    // F4 리뷰 반영: 폴백 출처(usage dict)는 입력과 출력 토큰 모두에 같은 불확실성을 준다(가정 1).
    // 입력에만 "대략"을 붙이면 출력 토큰이 마치 정확한 값처럼 보인다.
    const usage: GenerationUsage = {
      ...emptyUsage(), calls: 1, input_tokens: 10, output_tokens: 5, duration_ms: 100, cost_usd: 0.1,
      records: [{ purpose: "generate", ok: true, usage: callUsage({ token_source: "usage" }) }],
    };
    expect(formatUsage(usage)).toContain("대략 입력");
    expect(formatUsage(usage)).toContain("대략 출력");
  });

  it("실제 모델이 있으면 앞에 붙인다", () => {
    const usage: GenerationUsage = {
      ...emptyUsage(), calls: 1, models: ["claude-sonnet-4-5-20250929"],
      input_tokens: 10, output_tokens: 5, duration_ms: 100, cost_usd: 0.1,
      records: [{ purpose: "generate", ok: true, usage: callUsage() }],
    };
    expect(formatUsage(usage)).toMatch(/^AI 사용량: claude-sonnet-4-5-20250929 로 호출/);
  });
});

describe("sumUsage", () => {
  it("둘 다 값이 있으면 합산하고 records를 이어붙인다", () => {
    const a: GenerationUsage = {
      ...emptyUsage(), calls: 1, models: ["m1"],
      records: [{ purpose: "generate", ok: true, usage: callUsage({
        model: "m1", input_tokens: 10, output_tokens: 5,
        cache_read_tokens: 0, cache_creation_tokens: 0, duration_ms: 100, duration_api_ms: 90, cost_usd: 0.01,
      }) }],
    };
    const b: GenerationUsage = {
      ...emptyUsage(), calls: 1, models: ["m1"],
      records: [{ purpose: "generate", ok: true, usage: callUsage({
        model: "m1", input_tokens: 20, output_tokens: 15,
        cache_read_tokens: 0, cache_creation_tokens: 0, duration_ms: 200, duration_api_ms: 180, cost_usd: 0.02,
      }) }],
    };
    const sum = sumUsage([a, b]);
    expect(sum.calls).toBe(2);
    expect(sum.input_tokens).toBe(30);
    expect(sum.output_tokens).toBe(20);
    expect(sum.duration_ms).toBe(300);
    expect(sum.cost_usd).toBeCloseTo(0.03);
    expect(sum.models).toEqual(["m1"]);
    expect(sum.records).toHaveLength(2);
  });

  it("하나가 null이면 합계가 null이고 missing에 그 필드가 실린다", () => {
    const a: GenerationUsage = {
      ...emptyUsage(), calls: 1, cost_usd: 1.0,
      records: [{ purpose: "generate", ok: true, usage: callUsage({ cost_usd: 1.0 }) }],
    };
    const b: GenerationUsage = {
      ...emptyUsage(), calls: 1,
      records: [{ purpose: "generate", ok: true, usage: callUsage({ cost_usd: null }) }],
    };
    const sum = sumUsage([a, b]);
    expect(sum.cost_usd).toBeNull();
    expect(sum.missing).toContain("cost_usd");
  });

  it("unmeasured_calls를 더한다", () => {
    const a: GenerationUsage = {
      ...emptyUsage(), calls: 1, unmeasured_calls: 1,
      records: [{ purpose: "generate", ok: false, usage: null }],
    };
    const b: GenerationUsage = {
      ...emptyUsage(), calls: 1, unmeasured_calls: 0,
      records: [{ purpose: "generate", ok: true, usage: callUsage() }],
    };
    const sum = sumUsage([a, b]);
    expect(sum.unmeasured_calls).toBe(1);
    expect(sum.calls).toBe(2);
  });

  it("빈 목록을 주면 호출 0회의 빈 합계를 돌려준다", () => {
    const sum = sumUsage([]);
    expect(sum.calls).toBe(0);
    expect(sum.records).toEqual([]);
  });
});
