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
      baseUrl: "",
      override: {
        fetch: {
          includeHttpResponseReturnType: false,
        },
        mutator: {
          path: "./lib/api/client.ts",
          name: "apiRequest",
        },
      },
    },
  },
});
