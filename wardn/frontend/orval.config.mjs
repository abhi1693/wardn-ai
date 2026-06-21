import { defineConfig } from "orval";

export default defineConfig({
  wardnApi: {
    input: {
      target: "./openapi/wardn-api.json",
    },
    output: {
      mode: "tags-split",
      target: "./lib/api/generated/wardn.ts",
      schemas: "./lib/api/generated/model",
      client: "fetch",
      clean: true,
      baseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
    },
  },
});
