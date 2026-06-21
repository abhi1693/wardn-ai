import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  {
    ignores: ["lib/api/generated/**"],
  },
  ...nextVitals,
  ...nextTypescript,
];

export default config;
