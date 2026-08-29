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
  },
});
