// 보고 목적 표와 판정 (D3b-5). 칸 표와 길이 상한은 서버가 쓰는 고정 파일과 비교한다(서버 시험이 같은 파일을 서버 표와
// 비교한다). 지시문이 읽는 값의 판정은 서버의 purpose_prompt_values와 같은 규칙이다
import fixture from "../../../backend/tests/fixtures/report-purpose-fields.json";
import type { Deck } from "../api/client";
import {
  DETAIL_MAX, KEY_MESSAGE_MAX, OUTCOME_OTHER_MAX, PURPOSE_SCREEN_FIELDS, REPORT_DETAIL_FIELDS, REPORT_TYPES, hiddenInputs,
  isBlank, purposeMetaEqual, purposePromptValues, typeConfirmed,
} from "./reportPurpose";

const base: Deck["meta"] = { title: "제목", report_type: "weekly", audience: "", presenter: "", preset_overrides: {} };

test("유형별 추가 입력 칸과 길이 상한이 서버 표와 같다", () => {
  expect(Object.fromEntries(Object.entries(REPORT_DETAIL_FIELDS).map(([k, v]) => [k, v.map((pair) => [...pair])])))
    .toEqual(fixture.fields);
  expect({ key_message: KEY_MESSAGE_MAX, desired_outcome_other: OUTCOME_OTHER_MAX, detail: DETAIL_MAX }).toEqual(fixture.limits);
  expect(REPORT_TYPES.map(([value]) => value).sort()).toEqual(Object.keys(fixture.fields).sort());
});

test("지시문이 읽는 값은 앞뒤 공백을 지우고 숨은 입력을 빼며 기타 설명은 기타일 때만 넣는다", () => {
  expect(purposePromptValues(base)).toEqual({});
  expect(purposePromptValues({ ...base, key_message: "  핵심\n", desired_outcome: "facts", desired_outcome_other: "숨김",
    report_details: { "weekly.period": " 10월 ", "ir.investment_stage": "숨김", "weekly.baseline": "  " } }))
    .toEqual({ key_message: "핵심", desired_outcome: "facts", "detail.period": "10월" });
  expect(purposePromptValues({ ...base, desired_outcome: "other", desired_outcome_other: " 설명 " }))
    .toEqual({ desired_outcome: "other", desired_outcome_other: "설명" });
});

test("숨은 입력은 다른 유형의 비어 있지 않은 추가 입력과 기타가 아닐 때의 기타 설명이다", () => {
  expect(hiddenInputs({ ...base, desired_outcome: "facts", desired_outcome_other: "설명",
    report_details: { "weekly.period": "10월", "ir.investment_stage": "시드", "data.scope": " " } }))
    .toEqual({ details: ["ir.investment_stage"], other: true });
  expect(hiddenInputs({ ...base, desired_outcome: "other", desired_outcome_other: "설명" }).other).toBe(false);
});

test("저장 비교는 빈 문자열과 없는 칸, 공백만 있는 추가 입력과 없는 칸을 같게 본다 (D3b-1 리뷰 R13)", () => {
  expect(purposeMetaEqual(base, { ...base, key_message: "", desired_outcome_other: "", report_details: { "weekly.period": " " } }))
    .toBe(true);
  expect(purposeMetaEqual(base, { ...base, report_type_confirmed: true })).toBe(false);
  expect(purposeMetaEqual(base, { ...base, key_message: "핵심" })).toBe(false);
  expect(purposeMetaEqual(base, { ...base, report_details: { "ir.investment_stage": "시드" } })).toBe(false);
});

test("빈 값 판정은 서버(Python str.isspace)와 같은 공백 문자 집합을 쓴다 (D3b-5 리뷰 R5)", () => {
  // 서버 시험 test_is_blank_matches_the_screen과 같은 표다
  expect(isBlank("﻿")).toBe(false);
  expect(isBlank("\x1f")).toBe(true);
  expect(isBlank("\x85")).toBe(true);
  expect(isBlank(" \t\n　")).toBe(true);
  expect(purposePromptValues({ ...base, key_message: "\x1f핵심\x85" }).key_message).toBe("핵심");
});

test("보고 정보 칸 목록은 서버와 같고, 저장 비교는 그 칸을 모두 본다 (β 묶음 리뷰 B6)", () => {
  expect([...PURPOSE_SCREEN_FIELDS].sort()).toEqual(fixture.screen_fields);
  const changed: Record<(typeof PURPOSE_SCREEN_FIELDS)[number], Partial<Deck["meta"]>> = {
    title: { title: "다른 제목" }, presenter: { presenter: "팀" }, audience: { audience: "임원" },
    report_type: { report_type: "ir" }, report_type_confirmed: { report_type_confirmed: true },
    key_message: { key_message: "핵심" }, desired_outcome: { desired_outcome: "facts" },
    desired_outcome_other: { desired_outcome_other: "설명" }, report_details: { report_details: { "weekly.period": "10월" } },
  };
  for (const field of PURPOSE_SCREEN_FIELDS) expect(purposeMetaEqual(base, { ...base, ...changed[field] })).toBe(false);
});

test("저장 비교는 보고자와 피보고자의 없음과 빈 값을 같게 본다 (변형 P20, M34)", () => {
  const { presenter: _p, audience: _a, ...rest } = base;
  expect(purposeMetaEqual(rest as Deck["meta"], base)).toBe(true);
});

test("유형 확인은 확인 표시가 있거나 기본 유형이 아니면 참이다 (변형 P19, M33)", () => {
  expect(typeConfirmed({ ...base, report_type: "weekly" })).toBe(true);
  expect(typeConfirmed({ ...base, report_type: "research" })).toBe(false);
  expect(typeConfirmed({ ...base, report_type: "research", report_type_confirmed: true })).toBe(true);
});
