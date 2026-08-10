import { spawn } from "node:child_process";

const frontendPort = Number(process.env.WARDN_CYPRESS_FRONTEND_PORT ?? 3200);
const backendPort = Number(process.env.WARDN_CYPRESS_BACKEND_PORT ?? 4200);
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const backendUrl = `http://127.0.0.1:${backendPort}`;
const sessionCookieName =
  process.env.WARDN_CYPRESS_SESSION_COOKIE_NAME ?? "wardn_cypress_session";
const selectedSpec = process.env.WARDN_CYPRESS_SPEC?.trim() ?? "";
const services = [];

function run(command, args, env = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { env, stdio: "inherit" });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${command} exited with ${signal ?? code}`));
    });
  });
}

function start(command, args, env) {
  const child = spawn(command, args, {
    detached: true,
    env,
    stdio: "inherit",
  });
  services.push(child);
  return child;
}

async function waitFor(url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // The service is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function stopServices() {
  for (const child of services.reverse()) {
    if (child.pid && child.exitCode === null) {
      try {
        process.kill(-child.pid, "SIGTERM");
      } catch {
        child.kill("SIGTERM");
      }
    }
  }
}

async function main() {
  const buildEnv = {
    ...process.env,
    NEXT_PUBLIC_API_BASE_URL: backendUrl,
    NEXT_PUBLIC_SITE_URL: frontendUrl,
  };
  if (process.env.WARDN_CYPRESS_SKIP_BUILD !== "1") {
    await run("npm", ["run", "build"], buildEnv);
    await run("npm", ["run", "e2e:prepare"], buildEnv);
  }

  start("node", ["cypress/mock-backend.mjs"], {
    ...process.env,
    WARDN_CYPRESS_BACKEND_PORT: String(backendPort),
    WARDN_CYPRESS_FRONTEND_PORT: String(frontendPort),
    WARDN_SESSION_COOKIE_NAME: sessionCookieName,
  });
  await waitFor(`${backendUrl}/__test/health`, 30_000);

  start("node", [".next/standalone/wardn/frontend/server.js"], {
    ...process.env,
    HOSTNAME: "127.0.0.1",
    NEXT_PUBLIC_SITE_URL: frontendUrl,
    PORT: String(frontendPort),
    WARDN_BACKEND_URL: backendUrl,
    WARDN_SESSION_COOKIE_NAME: sessionCookieName,
  });
  await waitFor(`${frontendUrl}/login`);

  const cypressArgs = ["exec", "--", "cypress", "run", "--e2e", "--browser", "electron"];
  if (selectedSpec) {
    cypressArgs.push("--spec", selectedSpec);
  }
  await run("npm", cypressArgs, {
    ...process.env,
    WARDN_CYPRESS_BACKEND_PORT: String(backendPort),
    WARDN_CYPRESS_FRONTEND_PORT: String(frontendPort),
    WARDN_CYPRESS_SESSION_COOKIE_NAME: sessionCookieName,
  });
}

process.on("SIGINT", () => {
  stopServices();
  process.exit(130);
});
process.on("SIGTERM", () => {
  stopServices();
  process.exit(143);
});

try {
  await main();
} finally {
  stopServices();
}
