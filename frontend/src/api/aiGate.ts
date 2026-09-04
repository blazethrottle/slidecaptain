// AI 전송 고지 관문 (계획서 B3, 가정 5): 브라우저 탭 단위로 동의를 기억하고, AI 호출 3종은
// 이 모듈의 ensureConsent()를 거친 뒤에만 나간다. 동의는 sessionStorage에 남겨 탭을 닫으면
// 사라지고 새로고침에는 남는다(설계서 2.6의 3항). sessionStorage 접근이 막힌 환경(일부 비공개
// 모드)에서는 메모리로만 동작한다(그 환경에서는 새로고침마다 다시 묻는다. "틀렸을 가능성" 절).
const STORAGE_KEY = "slidecaptain.ai-consent";

type Prompter = () => Promise<boolean>;

let prompter: Prompter | null = null;
let memoryConsent = false;
let pendingPrompt: Promise<boolean> | null = null;

function readConsent(): boolean {
  try {
    return sessionStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return memoryConsent;
  }
}

function writeConsent(value: boolean): void {
  memoryConsent = value;  // sessionStorage 실패와 무관하게 이 탭의 메모리에는 남긴다
  try {
    if (value) sessionStorage.setItem(STORAGE_KEY, "1");
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // sessionStorage 접근이 막힌 환경: 메모리로만 유지한다
  }
}

export function hasConsent(): boolean {
  return readConsent();
}

export function grantConsent(): void {
  writeConsent(true);
}

export function revokeConsent(): void {
  writeConsent(false);
}

/** 대화 상자를 띄우고 사용자의 선택을 기다리는 함수를 등록한다(ProjectView가 마운트 시 등록). */
export function setConsentPrompter(fn: Prompter | null): void {
  prompter = fn;
}

/**
 * 동의가 있으면 즉시 참을 돌려주고, 없으면 등록된 프롬프터를 불러 사용자의 선택을 기다린다.
 * 프롬프터가 없으면 거짓이다. 겹친 호출은 같은 프라미스를 공유해 프롬프터를 한 번만 부른다.
 */
export function ensureConsent(): Promise<boolean> {
  if (hasConsent()) return Promise.resolve(true);
  if (!prompter) return Promise.resolve(false);
  if (!pendingPrompt) {
    pendingPrompt = prompter().then((granted) => {
      if (granted) grantConsent();
      pendingPrompt = null;
      return granted;
    });
  }
  return pendingPrompt;
}
