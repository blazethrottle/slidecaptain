import "@testing-library/jest-dom/vitest";

// 시험 환경의 BroadcastChannel (개정판 D3a-6 리뷰 S5). Node의 채널은 같은 프로세스의 다른 스레드(다른 시험 파일)에도
// 메시지를 전하므로, 같은 시험 파일 안의 채널 사이에만 전하는 구현으로 바꾼다. 표준대로 보낸 객체는 자기 메시지를
// 받지 않고, 메시지는 복사되어 비동기로 도착한다
class FileChannel {
  static open = new Set<FileChannel>();
  onmessage: ((event: MessageEvent) => void) | null = null;
  private closed = false;
  constructor(readonly name: string) { FileChannel.open.add(this); }
  postMessage(data: unknown): void {
    if (this.closed) throw new DOMException("채널이 닫혔습니다.", "InvalidStateError");
    const copy = structuredClone(data);
    for (const other of FileChannel.open) {
      if (other === this || other.name !== this.name) continue;
      setTimeout(() => { if (!other.closed) other.onmessage?.(new MessageEvent("message", { data: copy })); }, 0);
    }
  }
  close(): void { this.closed = true; FileChannel.open.delete(this); }
  addEventListener(): void {}
  removeEventListener(): void {}
}
globalThis.BroadcastChannel = FileChannel as unknown as typeof BroadcastChannel;
