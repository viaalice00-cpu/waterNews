import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 모드(npm run dev): 화면은 5173 포트, /api 요청은 Python 서버(8080)로 전달
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
