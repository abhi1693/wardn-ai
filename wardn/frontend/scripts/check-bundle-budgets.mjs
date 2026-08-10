import { readFile } from "node:fs/promises";

const statsPath = new URL("../.next/diagnostics/route-bundle-stats.json", import.meta.url);
const budgetsPath = new URL("../bundle-budgets.json", import.meta.url);

const [stats, budgets] = await Promise.all([
  readFile(statsPath, "utf8").then(JSON.parse),
  readFile(budgetsPath, "utf8").then(JSON.parse),
]);
const statsByRoute = new Map(stats.map((entry) => [entry.route, entry]));
const failures = [];

for (const [route, budget] of Object.entries(budgets)) {
  const entry = statsByRoute.get(route);
  if (!entry) {
    failures.push(`${route}: route is missing from analyzer output`);
    continue;
  }
  const actual = entry.firstLoadUncompressedJsBytes;
  const usage = ((actual / budget) * 100).toFixed(1);
  console.log(`${route}: ${actual.toLocaleString()} / ${budget.toLocaleString()} bytes (${usage}%)`);
  if (actual > budget) {
    failures.push(`${route}: ${actual.toLocaleString()} bytes exceeds ${budget.toLocaleString()}`);
  }
}

if (failures.length > 0) {
  console.error(`\nBundle budget failures:\n${failures.map((failure) => `- ${failure}`).join("\n")}`);
  process.exitCode = 1;
}
