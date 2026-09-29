import { resolve } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [tailwindcss()],
  base: "/static/dist/",
  build: {
    chunkSizeWarningLimit: 600,
    outDir: resolve(import.meta.dirname, "../src/newsroom/static/dist"),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(import.meta.dirname, "src/main.js"),
      output: {
        entryFileNames: "app.js",
        assetFileNames: (info) =>
          info.names?.some((name) => name.endsWith(".css")) ? "app.css" : "assets/[name]-[hash][extname]",
      },
    },
  },
});
