import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy so the frontend never needs CORS config on the FastAPI side:
// requests to /api/* and /health are forwarded to uvicorn on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
