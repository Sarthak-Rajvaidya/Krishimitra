import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Two pages: the main app (index.html) and the separate IoT monitoring site (iot.html).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
  build: { rollupOptions: { input: { main: "index.html", iot: "iot.html" } } },
  test: { environment: "node", globals: true },
});
