import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  {
    ignores: [
      "cypress/downloads/**",
      "cypress/screenshots/**",
      "cypress/videos/**",
      "lib/api/generated/**",
    ],
  },
  ...nextVitals,
  ...nextTypescript,
];

export default config;
