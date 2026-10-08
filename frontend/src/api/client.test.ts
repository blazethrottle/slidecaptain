import { emptyUsage } from "../test/usage";
import * as aiGate from "./aiGate";
import { AiConsentDeclined, api, followJob, resetEtags } from "./client";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
beforeEach(() => {
  resetEtags();
  vi.spyOn(api, "getStatus").mockResolvedValue({
    provider: "subscription", model: "sonnet", checked_at: "", login: { logged_in: true },
  });
});  // ETag 맵은 모듈 전역이라 테스트 사이에 새지 않게 비운다

it("오류 응답의 detail을 ApiError 메시지로 만든다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "자료가 너무 큽니다" }), { status: 422 }),
  ));
  await expect(api.listProjects()).rejects.toThrowError("자료가 너무 큽니다");
});

it("보고 계획 오류의 상태와 문자열 코드를 detail과 함께 보존한다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    detail: "자료가 바뀌었습니다", code: "stale_story_plan",
  }), { status: 409 })));
  await expect(api.listProjects()).rejects.toMatchObject({
    status: 409, code: "stale_story_plan", message: "자료가 바뀌었습니다",
  });
});

it.each([null, { private: "input" }, ["stale_story_plan"]])("문자열이 아닌 오류 코드는 보존하지 않는다: %j", async (code) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    detail: "다른 오류", code,
  }), { status: 409 })));
  await expect(api.listProjects()).rejects.toMatchObject({ code: undefined, message: "다른 오류" });
});

it("입력 검사의 메시지만 표시하고 원래 입력이나 내부 오류 객체는 노출하지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [
    { msg: "Value error, 같은 방향과 종류의 관계가 중복되었습니다", input: "private-input", ctx: { error: "internal" } },
    null, { other: "ignore" },
  ] }), { status: 422 })));
  await expect(api.listProjects()).rejects.toMatchObject({
    status: 422, message: "같은 방향과 종류의 관계가 중복되었습니다",
  });
});

it("성공 응답의 JSON을 그대로 돌려준다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify([{ name: "p1", title: "t", updated_at: "", status: "ok" }]), { status: 200 }),
  ));
  const projects = await api.listProjects();
  expect(projects[0].name).toBe("p1");
});

it("스냅샷 여부를 쿼리로 보낸다", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.putDeck("p1", { schema_version: 1, meta: { title: "t" } } as never, false);
  expect(fetchMock.mock.calls[0][0]).toContain("/deck?snapshot=false");
});

it("자료 파일 업로드는 파일 본문을 그대로 보내고 JSON 헤더를 붙이지 않는다", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ filename: "리서치.md", chars: 3 }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const file = new File(["abc"], "리서치.md", { type: "text/markdown" });
  const result = await api.uploadSource("p1", file, true);
  expect(result.filename).toBe("리서치.md");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(`/api/projects/p1/sources/${encodeURIComponent("리서치.md")}/upload?overwrite=true`);
  expect(init.method).toBe("POST");
  expect(init.body).toBe(file);
  const headers = new Headers(init.headers ?? {});
  expect(headers.has("Content-Type")).toBe(false);
  expect(headers.get("X-Requested-With")).toBe("SlideCaptain");  // 서버가 요구하는 앱 식별 헤더
});

it("업로드 오류 응답의 detail도 ApiError로 만든다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "같은 이름의 자료가 이미 있습니다: a.md" }), { status: 409 }),
  ));
  await expect(api.uploadSource("p1", new File(["x"], "a.md"), false))
    .rejects.toMatchObject({ status: 409, message: "같은 이름의 자료가 이미 있습니다: a.md" });
});

it("모든 요청에 SlideCaptain 표식 헤더를 붙인다", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.listProjects();
  const [, init] = fetchMock.mock.calls[0];
  const headers = new Headers((init as RequestInit).headers ?? {});
  expect(headers.get("X-Requested-With")).toBe("SlideCaptain");
});

it("getDeck 뒤 putDeck은 If-Match를 보내고, 응답 ETag로 다음 If-Match가 바뀐다", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1 }), {
      status: 200, headers: { ETag: '"etag-1"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), {
      status: 200, headers: { ETag: '"etag-2"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.getDeck("p1");
  await api.putDeck("p1", { schema_version: 1 } as never, false);
  const put1Init = fetchMock.mock.calls[1][1] as RequestInit;
  expect(new Headers(put1Init.headers ?? {}).get("If-Match")).toBe('"etag-1"');
  await api.putDeck("p1", { schema_version: 1 } as never, false);
  const put2Init = fetchMock.mock.calls[2][1] as RequestInit;
  expect(new Headers(put2Init.headers ?? {}).get("If-Match")).toBe('"etag-2"');
});

it("도식 보고 계획 연결 확인은 프로젝트 ETag와 앱 표식을 함께 보낸다", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1 }), {
      status: 200, headers: { ETag: '"etag-1"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1 }), {
      status: 200, headers: { ETag: '"etag-1"' },
    }));
  vi.stubGlobal("fetch", fetchMock);
  await api.getDeck("합성 보고");
  await api.reconcileDiagramStory("합성 보고", {
    deck: { schema_version: 1 } as never, chapter_id: "diagram-1", role: "evidence", claim_ids: ["claim-1"],
  });
  const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
  expect(url).toBe(`/api/projects/${encodeURIComponent("합성 보고")}/story-plan/diagram`);
  expect(init.method).toBe("POST");
  const headers = new Headers(init.headers);
  expect(headers.get("X-Requested-With")).toBe("SlideCaptain");
  expect(headers.get("If-Match")).toBe('"etag-1"');
});

it("늦게 도착한 도식 연결 응답이 이후 저장본의 ETag를 되돌리지 않는다", async () => {
  let finishCheck!: (response: Response) => void;
  const pendingCheck = new Promise<Response>(resolve => { finishCheck = resolve; });
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response("{}", { headers: { ETag: '"etag-1"' } }))
    .mockReturnValueOnce(pendingCheck)
    .mockResolvedValueOnce(new Response('{"ok":true}', { headers: { ETag: '"etag-2"' } }))
    .mockResolvedValueOnce(new Response('{"ok":true}'));
  vi.stubGlobal("fetch", fetchMock);
  await api.getDeck("p1");
  const checking = api.reconcileDiagramStory("p1", {
    deck: {} as never, chapter_id: "diagram-1", role: "evidence", claim_ids: ["claim-1"],
  });
  // 작성 창을 닫고 편집을 저장한 뒤 취소한 확인 요청의 응답이 도착한다.
  await api.putDeck("p1", {} as never, false);
  finishCheck(new Response("{}", { headers: { ETag: '"etag-1"' } }));
  await checking;
  await api.putDeck("p1", {} as never, false);
  const init = fetchMock.mock.calls[3][1] as RequestInit;
  expect(new Headers(init.headers).get("If-Match")).toBe('"etag-2"');
});

it("ETag를 모르면 If-Match를 보내지 않는다", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.putDeck("p1", { schema_version: 1 } as never, false);
  const init = fetchMock.mock.calls[0][1] as RequestInit;
  expect(new Headers(init.headers ?? {}).has("If-Match")).toBe(false);
});

// AI 전송 고지 관문 배선 (계획서 B3): 화면 테스트는 api를 통째로 목 처리하므로 관문 배선을 검증할
// 수 없다. 여기서는 fetch만 스텁하고 aiGate.ensureConsent를 spy해 client.ts의 실제 구현을 검증한다.
it("동의가 있으면 구조안 생성 요청에 X-AI-Consent 헤더를 붙인다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(true);
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", structure: null, usage: emptyUsage(), raw_text: "", unverified_numbers: [],
      format_retried: false }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.generateStructure("p1", {});
  expect(aiGate.ensureConsent).toHaveBeenCalledTimes(1);
  const [, init] = fetchMock.mock.calls[0];
  expect(new Headers((init as RequestInit).headers ?? {}).get("X-AI-Consent")).toBe("SlideCaptain");
});

it("동의가 없으면 구조안 생성은 fetch를 부르지 않고 AiConsentDeclined를 던진다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(false);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(api.generateStructure("p1", {})).rejects.toBeInstanceOf(AiConsentDeclined);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("장 생성도 동의 관문을 거쳐 헤더를 붙인다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(true);
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", slots: null, usage: emptyUsage(), raw_text: "", warnings: [],
      unverified_numbers: [], format_retried: false, condensed: false }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.generateChapter("p1", "c1");
  expect(aiGate.ensureConsent).toHaveBeenCalledTimes(1);
  const [, init] = fetchMock.mock.calls[0];
  expect(new Headers((init as RequestInit).headers ?? {}).get("X-AI-Consent")).toBe("SlideCaptain");
});

it("장 생성은 동의가 없으면 fetch를 부르지 않는다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(false);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(api.generateChapter("p1", "c1")).rejects.toBeInstanceOf(AiConsentDeclined);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("축약도 동의 관문을 거쳐 헤더를 붙인다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(true);
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", slots: null, usage: emptyUsage(), raw_text: "", warnings: [],
      unverified_numbers: [], format_retried: false, condensed: false }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.condenseChapter("p1", "c1", { template: "bullet_box", bullets: [], conclusion: "", footnote: "" });
  expect(aiGate.ensureConsent).toHaveBeenCalledTimes(1);
  const [, init] = fetchMock.mock.calls[0];
  expect(new Headers((init as RequestInit).headers ?? {}).get("X-AI-Consent")).toBe("SlideCaptain");
});

it("축약은 동의가 없으면 fetch를 부르지 않는다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(false);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(api.condenseChapter("p1", "c1",
    { template: "bullet_box", bullets: [], conclusion: "", footnote: "" }))
    .rejects.toBeInstanceOf(AiConsentDeclined);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("다른 프로젝트 이름은 다른 ETag 키다", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1 }), {
      status: 200, headers: { ETag: '"p1-etag"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.getDeck("p1");
  await api.putDeck("p2", { schema_version: 1 } as never, false);
  const init = fetchMock.mock.calls[1][1] as RequestInit;
  expect(new Headers(init.headers ?? {}).has("If-Match")).toBe(false);
});

it("확인한 연결 식별값을 생성 요청에 고정해서 보낸다", async () => {
  vi.mocked(api.getStatus).mockResolvedValue({ provider: "chatgpt", model: "gpt-test", selection_id: "selection-one",
    checked_at: "", login: { logged_in: true } });
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(true);
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" })));
  vi.stubGlobal("fetch", fetchMock);
  await api.generateStructure("p", {});
  expect(aiGate.ensureConsent).toHaveBeenCalledWith("selection-one", expect.objectContaining({ provider: "chatgpt" }));
  expect(new Headers(fetchMock.mock.calls[0][1].headers).get("X-AI-Selection")).toBe("selection-one");
});

it("로그인 확인 실패와 식별값 없는 새 연결에서는 문서를 보내지 않는다", async () => {
  const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
  vi.mocked(api.getStatus).mockResolvedValue({ provider: "chatgpt", model: "gpt-test", checked_at: "", login: { logged_in: false } });
  await expect(api.generateStructure("p", {})).rejects.toThrow("로그인 상태");
  vi.mocked(api.getStatus).mockResolvedValue({ provider: "chatgpt", model: "gpt-test", checked_at: "", login: { logged_in: true } });
  await expect(api.generateStructure("p", {})).rejects.toThrow("AI 설정");
  expect(fetchMock).not.toHaveBeenCalled();
});
it("계산 문구 대조는 현재 편집본을 앱 헤더와 함께 보내고 AI 동의를 요청하지 않는다", async () => {
  const consent = vi.spyOn(aiGate, "ensureConsent");
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "not_run" }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const draft = { schema_version: 1, slides: [] } as never;
  await api.reviewNumbers("합성 자료", draft);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe(`/api/projects/${encodeURIComponent("합성 자료")}/review/numbers`);
  expect(JSON.parse(init.body as string)).toEqual(draft);
  const headers = new Headers(init.headers);
  expect(headers.get("X-Requested-With")).toBe("SlideCaptain");
  expect(headers.has("X-AI-Consent")).toBe(false);
  expect(consent).not.toHaveBeenCalled();
});

it("재작성은 동의 전의 ETag에 고정하고 미리보기는 ETag 캐시를 변경하지 않는다", async () => {
  let allow!: (v:boolean)=>void;
  vi.spyOn(aiGate,"ensureConsent").mockReturnValue(new Promise(r=>{allow=r;}));
  const fetchMock=vi.fn()
    .mockResolvedValueOnce(new Response('{}',{headers:{ETag:'"original"'}}))
    .mockResolvedValueOnce(new Response('{"ok":true}',{headers:{ETag:'"newer"'}}))
    .mockResolvedValueOnce(new Response('{"status":"ok"}',{headers:{ETag:'"stale-preview"'}}))
    .mockResolvedValueOnce(new Response('{"ok":true}'));
  vi.stubGlobal("fetch",fetchMock);
  await api.getDeck("p1");
  const pending=api.rewriteStory("p1",{brief:{decision_question:"질문",audience:"",report_type:"research",reading_profile:"미지정",constraints:[]},instructions:""});
  await Promise.resolve();
  await api.putDeck("p1",{} as never,false);
  allow(true); await pending;
  expect(new Headers(fetchMock.mock.calls[2][1].headers).get("If-Match")).toBe('"original"');
  expect(new Headers(fetchMock.mock.calls[2][1].headers).get("X-AI-Consent")).toBe("SlideCaptain");
  await api.putDeck("p1",{} as never,false);
  expect(new Headers(fetchMock.mock.calls[3][1].headers).get("If-Match")).toBe('"newer"');
});

it("재작성 적용은 최신 캐시 대신 후보의 ETag를 보내고 저장 성공 뒤에만 진전시킨다",async()=>{
  const fetchMock=vi.fn()
    .mockResolvedValueOnce(new Response('{}',{headers:{ETag:'"cached-newer"'}}))
    .mockResolvedValueOnce(new Response('{}',{headers:{ETag:'"saved"'}}))
    .mockResolvedValueOnce(new Response('{"ok":true}'));
  vi.stubGlobal("fetch",fetchMock); await api.getDeck("p1");
  await api.applyStoryRewrite("p1",{base_etag:'"preview-base"',deck:{},sources_fingerprint:"a".repeat(64)} as never);
  expect(new Headers(fetchMock.mock.calls[1][1].headers).get("If-Match")).toBe('"preview-base"');
  expect(new Headers(fetchMock.mock.calls[1][1].headers).has("X-AI-Consent")).toBe(false);
  await api.putDeck("p1",{} as never,false);
  expect(new Headers(fetchMock.mock.calls[2][1].headers).get("If-Match")).toBe('"saved"');
});

// D2b-5a: 장 생성 묶음은 승인 반영의 ETag를 기준으로 등록하고, 서버가 장을 저장한 뒤에는 덱을 다시 읽어야
// 다음 자동 저장이 412를 받지 않는다
it("묶음 등록은 저장 ETag를 바꾸지 않고, 묶음 뒤 덱을 다시 읽으면 다음 저장이 새 ETag를 보낸다", async () => {
  const json = (body: unknown, etag?: string) => new Response(JSON.stringify(body),
    { status: 200, headers: etag ? { ETag: etag } : {} });
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(json({ schema_version: 1 }, '"etag-1"'))   // getDeck
    .mockResolvedValueOnce(json({ ok: true }, '"etag-2"'))            // 승인 반영
    .mockResolvedValueOnce(json({ id: "job-1" }, '"etag-other"'))     // 묶음 등록
    .mockResolvedValueOnce(json({ ok: false }))                       // 등록 직후 저장 (기준 ETag 확인용)
    .mockResolvedValueOnce(json({ schema_version: 1 }, '"etag-3"'))   // 묶음 뒤 다시 읽기
    .mockResolvedValueOnce(json({ ok: true }));                       // 첫 자동 저장
  vi.stubGlobal("fetch", fetchMock);
  await api.getDeck("p1");
  await api.putDeck("p1", { schema_version: 1 } as never, true);
  await api.startChapters("p1", ["c1", "c2"], { "X-AI-Consent": "SlideCaptain" }, "req1");
  const [url, init] = fetchMock.mock.calls[2] as [string, RequestInit];
  expect(url).toBe("/api/projects/p1/jobs");
  const headers = new Headers(init.headers ?? {});
  expect(headers.get("If-Match")).toBe('"etag-2"');
  expect(headers.get("X-AI-Consent")).toBe("SlideCaptain");
  expect(JSON.parse(init.body as string)).toEqual({ request_id: "req1", kind: "chapters", params: { chapter_ids: ["c1", "c2"] } });
  // 등록 응답의 ETag는 저장 기준을 바꾸지 않는다
  await api.putDeck("p1", { schema_version: 1 } as never, false);
  expect(new Headers((fetchMock.mock.calls[3][1] as RequestInit).headers ?? {}).get("If-Match")).toBe('"etag-2"');
  await api.getDeck("p1");
  await api.putDeck("p1", { schema_version: 1 } as never, false);
  expect(new Headers((fetchMock.mock.calls[5][1] as RequestInit).headers ?? {}).get("If-Match")).toBe('"etag-3"');
});

it("작업 조회는 실패해도 알리고 계속 조회하며, 끝난 상태를 돌려준다", async () => {
  const fetchJob = vi.fn()
    .mockRejectedValueOnce(new Error("일시 오류"))
    .mockResolvedValueOnce({ state: "running" })
    .mockResolvedValueOnce({ state: "succeeded" });
  const onUpdate = vi.fn();
  const onError = vi.fn();
  const final = await followJob(fetchJob as never, onUpdate, { intervalMs: 0, onError });
  expect(final).toEqual({ state: "succeeded" });
  expect(onError).toHaveBeenCalledTimes(1);
  expect(onUpdate.mock.calls.map(([v]) => v.state)).toEqual(["running", "succeeded"]);
});

it("작업 조회는 중단 신호를 받으면 더 조회하지 않는다", async () => {
  const controller = new AbortController();
  const fetchJob = vi.fn().mockImplementation(async () => { controller.abort(); return { state: "running" }; });
  await expect(followJob(fetchJob as never, () => {}, { intervalMs: 0, signal: controller.signal })).rejects.toThrow();
  expect(fetchJob).toHaveBeenCalledTimes(1);
});
