/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8765" },  // 개발 중 same-origin 유지 (CORS 불필요, 결정 7)
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
    clearMocks: true,  // 테스트마다 모의 호출 기록을 비운다 (파일 내 누적으로 인한 오탐 방지)
    // 시험 파일마다 프로세스를 나눈다. Node의 BroadcastChannel은 같은 프로세스의 스레드 사이에 메시지를 전하므로,
    // threads에서는 다른 파일의 채널 메시지가 화면 시험에 들어간다 (D3a-6 리뷰 S5)
    pool: "forks",
  },
});
