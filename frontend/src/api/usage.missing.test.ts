import fixture from "../../../backend/tests/fixtures/usage-missing.json";
import type { GenerationUsage } from "./client";
import { emptyUsage } from "../test/usage";
import { formatUsage, sumUsage } from "./usage";

const usage = fixture as GenerationUsage;

it("SDK 재시도 API 픽스처와 프런트 합산이 결측과 0을 동일하게 보존한다", () => {
  const parts = usage.records.map((record) => ({ ...emptyUsage(), records: [record] }));
  expect(sumUsage(parts)).toEqual(usage);
  expect(formatUsage(usage)).toBe(
    "AI 사용량: fixture-model 로 호출 2회(형식 재시도 1회 포함), 입력 12 토큰, 출력 토큰 미확인, " +
    "캐시 생성 토큰 미확인, 처리 0.2초, 참고 비용 $0 (AI 도구가 계산한 값으로 실제 청구액이 아닙니다)",
  );
});

it("입력이 없더라도 알려진 출력과 캐시 읽기는 표시한다", () => {
  const text = formatUsage({ ...usage, input_tokens: null, output_tokens: 5, cache_read_tokens: 10 });
  expect(text).toContain("입력 토큰 미확인, 출력 5 토큰, 캐시 읽기 10 토큰");
  expect(text).toContain("캐시 생성 토큰 미확인");
});

it("캐시 읽기 결측과 명시적 캐시 0을 구분한다", () => {
  const text = formatUsage({ ...usage, output_tokens: 5, cache_read_tokens: null, cache_creation_tokens: 0 });
  expect(text).toContain("캐시 읽기 토큰 미확인");
  expect(text).not.toContain("캐시 생성");
});

it("모든 토큰이 없으면 미확인으로 묶고 실제 0은 숫자로 표시한다", () => {
  expect(formatUsage(emptyUsage())).toContain("토큰 미확인");
  expect(formatUsage(emptyUsage())).not.toContain("캐시");
  const text = formatUsage({ ...usage, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0 });
  expect(text).toContain("입력 0 토큰, 출력 0 토큰");
  expect(text).not.toContain("캐시");
});
