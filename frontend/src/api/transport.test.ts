import { api } from './client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { appFetch, type DesktopBridge } from './transport';
afterEach(() => { delete window.slidecaptain; vi.unstubAllGlobals(); });
function native(request: DesktopBridge['request']) {
  window.slidecaptain = { request, cancelRequest: vi.fn().mockResolvedValue(undefined), chooseFiles: vi.fn(), chooseFolder: vi.fn(), openLogin: vi.fn() };
}
describe('desktop API transport', () => {
  it('allows live AbortSignals and cancels only the owning native request', async () => {
    const request = vi.fn().mockImplementation(() => new Promise(() => {})); native(request);
    const controller = new AbortController(); const pending = appFetch('/api/projects', { signal: controller.signal });
    expect(request).toHaveBeenCalledOnce(); controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(window.slidecaptain!.cancelRequest).toHaveBeenCalledWith(request.mock.calls[0][0].id);
  });
  it('does not start an already cancelled request', async () => {
    const request = vi.fn(); native(request); const controller = new AbortController(); controller.abort();
    await expect(appFetch('/api/projects', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    expect(request).not.toHaveBeenCalled();
  });
  it('routes the existing project API through the native bridge', async () => {
    const request = vi.fn().mockResolvedValue({ status: 200, statusText: '', headers: [], body: new TextEncoder().encode('[]') }); native(request);
    expect(await api.listProjects()).toEqual([]); expect(request).toHaveBeenCalled();
  });
  it('keeps the regular web transport when there is no native bridge', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('web')); vi.stubGlobal('fetch', fetch);
    await appFetch('/api/projects'); expect(fetch).toHaveBeenCalledWith('/api/projects', undefined);
  });
  it('passes ETag and app/consent headers through main without a renderer session token', async () => {
    const request = vi.fn().mockResolvedValue({ status: 412, statusText: '', headers: [['etag', 'new']], body: new TextEncoder().encode('{"detail":"conflict"}') }); native(request);
    const r = await appFetch('/api/projects/example/deck', { method: 'PUT', body: '{}', headers: { 'If-Match': 'old', 'X-Requested-With': 'SlideCaptain', 'X-AI-Consent': 'SlideCaptain' } });
    expect(r.status).toBe(412); expect(r.headers.get('etag')).toBe('new'); expect(await r.json()).toEqual({ detail: 'conflict' });
    const headers = request.mock.calls[0][0].headers; expect(headers['if-match']).toBe('old'); expect(headers['x-ai-consent']).toBe('SlideCaptain'); expect(headers['x-slidecaptain-session']).toBeUndefined();
  });
  it('sends selected file bytes unchanged', async () => {
    const request = vi.fn().mockResolvedValue({ status: 200, statusText: '', headers: [], body: new Uint8Array() }); native(request);
    await appFetch('/api/projects/example/sources/sample.txt/upload', { method: 'POST', body: new Blob(['합성 자료']) });
    expect(new TextDecoder().decode(request.mock.calls[0][0].body)).toBe('합성 자료');
  });
  it('does not attach a body to a 204 response', async () => {
    native(vi.fn().mockResolvedValue({ status: 204, statusText: '', headers: [], body: new Uint8Array() }));
    expect((await appFetch('/api/projects')).body).toBeNull();
  });
});
