/** Native requests pass through main; the session value never enters the renderer. */
export interface DesktopReply { status: number; statusText: string; headers: [string, string][]; body: Uint8Array }
export interface DesktopFiles { cancelled: boolean; files: { name: string; bytes: Uint8Array }[]; notes: { name: string; reason: string }[] }
export interface DesktopBridge {
  request(input: { id: string; path: string; method: string; headers: Record<string, string>; body?: string | Uint8Array }): Promise<DesktopReply>;
  cancelRequest(id: string): Promise<void>;
  chooseFiles(): Promise<DesktopFiles>;
  chooseFolder(): Promise<DesktopFiles>;
  openLogin(url: string): Promise<void>;
}
declare global { interface Window { slidecaptain?: DesktopBridge } }
export async function appFetch(path: string, init?: RequestInit): Promise<Response> {
  const bridge = window.slidecaptain;
  if (!bridge) return fetch(path, init);
  const signal = init?.signal;
  const abortError = () => new DOMException('요청을 취소했습니다.', 'AbortError');
  if (signal?.aborted) throw abortError();
  let body: string | Uint8Array | undefined;
  if (typeof init?.body === 'string') body = init.body;
  else if (init?.body instanceof Blob) {
    const blob = init.body;
    const buffer = typeof blob.arrayBuffer === 'function' ? await blob.arrayBuffer() : await new Promise<ArrayBuffer>((resolve, reject) => {
      const reader = new FileReader(); reader.onerror = () => reject(new Error('선택한 파일을 읽지 못했습니다.'));
      reader.onload = () => reader.result instanceof ArrayBuffer ? resolve(reader.result) : reject(new Error('파일 응답을 읽지 못했습니다.')); reader.readAsArrayBuffer(blob);
    });
    body = new Uint8Array(buffer);
  }
  else if (init?.body instanceof ArrayBuffer) body = new Uint8Array(init.body);
  else if (ArrayBuffer.isView(init?.body)) body = new Uint8Array(init.body.buffer, init.body.byteOffset, init.body.byteLength);
  else if (init?.body != null) throw new Error('Unsupported native request body.');
  if (signal?.aborted) throw abortError();
  const id = crypto.randomUUID();
  const reply = await new Promise<DesktopReply>((resolve, reject) => {
    const abort = () => { void bridge.cancelRequest(id).catch(() => {}); reject(abortError()); };
    signal?.addEventListener('abort', abort, { once: true });
    bridge.request({ id, path, method: init?.method ?? 'GET', headers: Object.fromEntries(new Headers(init?.headers)), body })
      .then(resolve, reject).finally(() => signal?.removeEventListener('abort', abort));
  });
  const bytes = new Uint8Array(reply.body);
  return new Response([204, 205, 304].includes(reply.status) ? null : bytes.buffer, { status: reply.status, statusText: reply.statusText, headers: reply.headers });
}
