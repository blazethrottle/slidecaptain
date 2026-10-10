import { useEffect, useId, useRef, useState } from "react";
import { api, messageOf, type AISettings, type LoginAttempt, type ProviderId } from "../api/client";
import { revokeConsent } from "../api/aiGate";

function safeLoginURL(value: string | null | undefined) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && ["auth.openai.com", "auth0.openai.com", "chatgpt.com"].includes(url.hostname)
      && !url.username && !url.password && (!url.port || url.port === "443") ? value : null;
  } catch { return null; }
}

/** One screen for both providers; identity entry belongs to the official browser. */
export function AISettingsPanel({ disabled = false }: { disabled?: boolean }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  // 프로젝트 화면에서는 상단 머리의 드로어로 겹쳐 뜬다. Esc로 닫고 초점을 여닫기 버튼으로 돌려준다 (D3a-2 리뷰 R7).
  // 문서 전체에서 받는다: 설정을 읽는 동안 여닫기 버튼이 잠겨 초점이 문서 본문으로 빠지기 때문이다
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); toggleRef.current?.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  const [settings, setSettings] = useState<AISettings | null>(null);
  const [provider, setProvider] = useState<ProviderId>("claude");
  const [model, setModel] = useState("");
  const [attempts, setAttempts] = useState<Partial<Record<ProviderId, LoginAttempt>>>({});
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = async (reset: boolean) => {
    const data = await api.getAISettings();
    setSettings(data);
    setAttempts(Object.fromEntries(data.providers.map(p => [p.id, p.login_attempt])));
    if (reset) {
      setProvider(data.selection.provider ?? "claude");
      setModel(data.selection.model ?? "");
    }
  };

  const run = async (fn: () => Promise<void>) => {
    setWorking(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError(messageOf(e)); }
    finally { setWorking(false); }
  };

  const pending = (Object.keys(attempts) as ProviderId[]).filter(p => attempts[p]?.state === "pending").join(",");
  useEffect(() => {
    if (!pending) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      for (const p of pending.split(",") as ProviderId[]) {
        try {
          const result = await api.getAILogin(p);
          if (cancelled) return;
          setAttempts(prev => ({ ...prev, [p]: result }));
          if (result.state === "succeeded") {
            revokeConsent();
            await load(false);
            if (!cancelled) window.dispatchEvent(new Event("slidecaptain:ai-selection"));
          }
        } catch (e) {
          if (!cancelled) {
            setError(messageOf(e));
            setAttempts(prev => ({ ...prev, [p]: { state: "failed", message: "로그인 상태를 확인하지 못했습니다. 다시 확인해 주세요." } }));
          }
        }
      }
      if (!cancelled) timer = setTimeout(poll, 2000);
    };
    timer = setTimeout(poll, 2000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [pending]);

  const current = settings?.providers.find(p => p.id === provider);
  const attempt = attempts[provider];
  const authURL = safeLoginURL(attempt?.auth_url);
  const locked = disabled || working || !!settings?.busy;
  const status = current?.login;
  const selectedName = settings?.providers.find(p => p.id === settings.selection.provider)?.label;
  const quickChoices = [
    { provider: "claude" as const, model: "sonnet", label: "Claude Sonnet" },
    { provider: "chatgpt" as const, model: "gpt-6-luna", label: "Codex LUNA" },
  ];
  const available = (service: ProviderId, modelId: string) =>
    !!settings?.providers.find(p => p.id === service)?.models.some(m => m.id === modelId);

  return <section className="ai-settings">
    <button ref={toggleRef} type="button" aria-expanded={open} aria-controls={id} disabled={disabled || working}
      onClick={() => {
        if (!open) void run(() => load(true));
        setOpen(!open);
      }}>AI 연결 및 모델</button>
    {open && <div id={id} className="ai-settings-body">
      <h2>AI 연결</h2>
      <p>서비스 선택 → 공식 계정 로그인 → 모델 선택과 저장 순서로 연결합니다.</p>
      {settings && <p className="hint">현재 적용: {selectedName} / {settings.selection.model}</p>}
      {working && <p role="status">처리 중...</p>}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <fieldset disabled={locked}>
        <legend>서비스와 모델</legend>
        <div className="actions" role="group" aria-label="모델 빠른 선택">
          {quickChoices.map(choice => <button key={choice.provider} type="button"
            disabled={!available(choice.provider, choice.model)}
            aria-pressed={provider === choice.provider && model === choice.model}
            onClick={() => {
              setProvider(choice.provider); setModel(choice.model);
              setNotice(""); setError("");
            }}>{choice.label}</button>)}
        </div>
        <p className="hint">사용할 모델을 직접 고른 뒤 선택 저장으로 확정하세요.</p>
        {settings && !available("chatgpt", "gpt-6-luna") && <p className="hint">
          Codex 모델 목록에서 LUNA를 찾지 못했습니다. 연결 상태를 다시 확인하거나 아래에서 다른 모델을 직접 선택하세요.
        </p>}
        <div className="field"><label>AI 서비스
          <select value={provider} onChange={e => {
            const next = e.target.value as ProviderId;
            setProvider(next);
            setModel(next === settings?.selection.provider ? settings.selection.model ?? ""
              : settings?.providers.find(p => p.id === next)?.models[0]?.id ?? "");
            setNotice(""); setError("");
          }}>
            <option value="claude">Claude</option><option value="chatgpt">Codex (ChatGPT)</option>
          </select>
        </label></div>
        {status && <p role="status">{status.logged_in === true
          ? `연결됨${status.account ? ` (${status.account})` : ""}. 실제 생성 성공 여부는 별도로 확인합니다.`
          : status.logged_in === false ? "로그인되지 않았습니다." : `연결 확인 필요: ${status.error ?? "상태 미상"}`}</p>}
        <p className="hint">{provider === "claude"
          ? "본인용 로컬 연결입니다. 이 PC의 Claude Code 계정을 사용하며 로그인은 Claude Code가 공식 브라우저에서 처리합니다."
          : "ChatGPT 계정으로 SlideCaptain 전용 연결을 만듭니다. 기존 Codex 앱의 로그인 설정은 그대로 유지됩니다."}</p>
        <div className="actions">
          {attempt?.state !== "pending" && <button onClick={() => void run(async () => {
            const result = await api.startAILogin(provider);
            setAttempts(prev => ({ ...prev, [provider]: result }));
            revokeConsent();
          })}>{status?.logged_in ? "다시 로그인" : "로그인 시작"}</button>}
          {attempt?.state === "pending" && <button onClick={() => void run(async () => {
            const result = await api.cancelAILogin(provider);
            setAttempts(prev => ({ ...prev, [provider]: result }));
          })}>로그인 대기 취소</button>}
          <button onClick={() => void run(() => load(false))}>연결 상태 다시 확인</button>
        </div>
        {attempt?.message && <p role="status">{attempt.message}</p>}
        {attempt?.state === "pending" && authURL && <p>
          <a className="ai-login-link" href={authURL} target="_blank" rel="noopener noreferrer">공식 로그인 페이지 열기</a>
        </p>}
        <div className="field"><label>언어모델
          <select value={model} onChange={e => setModel(e.target.value)} disabled={!current?.models.length}>
            {!current?.models.some(m => m.id === model) && <option value="">모델을 선택해 주세요</option>}
            {current?.models.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label></div>
        {current?.models_error && <p role="alert">{current.models_error}</p>}
        <p className="hint">{provider === "chatgpt" ? "설치된 Codex가 제공하는 모델 목록입니다. 계정별 이용 가능 여부와 한도는 실제 요청 시 확인됩니다."
          : "Sonnet, Opus, Haiku는 최신 버전을 가리키는 모델 별칭입니다. 계정과 한도에 따라 이용 가능 여부가 달라질 수 있습니다."}</p>
        <button disabled={!current?.models.some(m => m.id === model) || attempt?.state === "pending"}
          onClick={() => void run(async () => {
            await api.selectAI({ provider, model });
            revokeConsent();
            await load(true);
            window.dispatchEvent(new Event("slidecaptain:ai-selection"));
            setNotice("저장했습니다. 다음 생성부터 적용하며 전송 대상을 다시 확인합니다.");
          })}>선택 저장</button>
      </fieldset>
      {settings?.busy && <p role="status">생성이 끝나면 연결 설정을 변경할 수 있습니다.</p>}
      <p className="hint">로그인과 상태 확인은 문서를 전송하지 않습니다. 생성 시 선택한 서비스의 사용량이 소모됩니다.
        Claude Agent SDK 월 크레딧과 ChatGPT의 Codex 이용 한도는 웹 채팅 및 API 결제와 다를 수 있습니다.</p>
      <p className="hint">설치 안내: <a href="https://code.claude.com/docs/en/quickstart" target="_blank" rel="noopener noreferrer">Claude Code</a>
        {" / "}<a href="https://developers.openai.com/codex/cli/" target="_blank" rel="noopener noreferrer">Codex</a></p>
    </div>}
  </section>;
}
