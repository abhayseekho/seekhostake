import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built to dist/ and served by FastAPI at "/". In local dev, proxy API+auth to uvicorn on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8000",
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
