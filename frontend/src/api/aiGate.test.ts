import {
  ensureConsent, grantConsent, hasConsent, revokeConsent, setConsentPrompter,
} from "./aiGate";

beforeEach(() => {
  revokeConsent();
  setConsentPrompter(null);
});

it("동의가 없으면 프롬프터를 불러 확인을 기다린다", async () => {
  const prompter = vi.fn().mockResolvedValue(true);
  setConsentPrompter(prompter);
  const granted = await ensureConsent();
  expect(granted).toBe(true);
  expect(prompter).toHaveBeenCalledTimes(1);
  expect(hasConsent()).toBe(true);
});

it("확인하면 sessionStorage에 남아 두 번째 호출은 프롬프터 없이 참이다", async () => {
  const prompter = vi.fn().mockResolvedValue(true);
  setConsentPrompter(prompter);
  await ensureConsent();
  setConsentPrompter(null);  // 두 번째 호출이 프롬프터를 다시 부르면 등록이 없어 거짓이 될 것
  const granted = await ensureConsent();
  expect(granted).toBe(true);
  expect(prompter).toHaveBeenCalledTimes(1);
});

it("취소하면 거짓이고 저장하지 않는다", async () => {
  const prompter = vi.fn().mockResolvedValue(false);
  setConsentPrompter(prompter);
  const granted = await ensureConsent();
  expect(granted).toBe(false);
  expect(hasConsent()).toBe(false);
  // 다시 불러도 여전히 프롬프터를 거쳐야 한다(동의가 저장되지 않았으므로)
  const granted2 = await ensureConsent();
  expect(granted2).toBe(false);
  expect(prompter).toHaveBeenCalledTimes(2);
});

it("프롬프터 미등록이면 거짓이다", async () => {
  const granted = await ensureConsent();
  expect(granted).toBe(false);
});

it("겹친 두 호출은 프롬프터를 한 번만 부른다", async () => {
  let resolvePrompt: (v: boolean) => void = () => {};
  const prompter = vi.fn(() => new Promise<boolean>((resolve) => { resolvePrompt = resolve; }));
  setConsentPrompter(prompter);
  const p1 = ensureConsent();
  const p2 = ensureConsent();
  resolvePrompt(true);
  expect(await p1).toBe(true);
  expect(await p2).toBe(true);
  expect(prompter).toHaveBeenCalledTimes(1);
});

it("grantConsent로 미리 동의해 두면 프롬프터를 부르지 않는다", async () => {
  grantConsent();
  const prompter = vi.fn();
  setConsentPrompter(prompter);
  expect(await ensureConsent()).toBe(true);
  expect(prompter).not.toHaveBeenCalled();
});

it("sessionStorage가 던져도 죽지 않는다", async () => {
  const original = Object.getOwnPropertyDescriptor(window, "sessionStorage");
  Object.defineProperty(window, "sessionStorage", {
    configurable: true,
    get() { throw new Error("접근 차단"); },
  });
  try {
    const prompter = vi.fn().mockResolvedValue(true);
    setConsentPrompter(prompter);
    const granted = await ensureConsent();
    expect(granted).toBe(true);
    // sessionStorage가 막혀도 메모리로는 남아 같은 세션 안에서는 다시 묻지 않는다
    expect(hasConsent()).toBe(true);
  } finally {
    if (original) Object.defineProperty(window, "sessionStorage", original);
  }
});
