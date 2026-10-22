import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { test } from "node:test";

const runtimeRoot = new URL("../", import.meta.url);
function quote(value) {
  return "'" + value.replaceAll("'", "'\\''") + "'";
}

async function rpc(url, message, headers = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream", ...headers },
    body: JSON.stringify(message),
    signal: AbortSignal.timeout(5000),
  });
  assert.ok(response.ok, `RPC ${message.method}: HTTP ${response.status}`);
  if (message.id === undefined) return { response };
  const body = await response.text();
  const data = response.headers.get("content-type")?.includes("text/event-stream")
    ? body.split("\n").filter((line) => line.startsWith("data:")).map((line) => JSON.parse(line.slice(5))).find((item) => item.id === message.id)
    : JSON.parse(body);
  assert.equal(data.id, message.id);
  assert.equal(data.error, undefined);
  return { response, result: data.result };
}

test("production gateway flags bridge stdio initialization, discovery and tool calls", { timeout: 30000 }, async () => {
  const reservation = createServer();
  reservation.listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const port = reservation.address().port;
  await new Promise((resolve) => reservation.close(resolve));
  const command = [process.execPath, fileURLToPath(new URL("fixtures/server.mjs", import.meta.url))].map(quote).join(" ");
  const gateway = spawn(process.execPath, [
    fileURLToPath(new URL("node_modules/supergateway/dist/index.js", runtimeRoot)),
    "--stdio", command,
    "--outputTransport", "streamableHttp",
    "--port", String(port),
    "--host", "127.0.0.1",
    "--streamableHttpPath", "/mcp",
    "--healthEndpoint", "/health",
  ], { detached: true, stdio: ["ignore", "pipe", "pipe"] });
  let diagnostics = "";
  for (const stream of [gateway.stdout, gateway.stderr]) stream.on("data", (data) => { diagnostics = (diagnostics + data).slice(-4000); });
  const baseUrl = `http://127.0.0.1:${port}`;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 50; attempt++) {
      if (gateway.exitCode !== null) throw new Error(`Gateway exited: ${diagnostics}`);
      try { ready = (await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(500) })).ok; } catch { /* Still starting. */ }
      if (ready) break;
      await delay(100);
    }
    assert.ok(ready, diagnostics);
    const initialized = await rpc(`${baseUrl}/mcp`, {
      jsonrpc: "2.0", id: 1, method: "initialize",
      params: { protocolVersion: "2025-03-26", capabilities: {}, clientInfo: { name: "wardn-smoke", version: "1.0.0" } },
    });
    assert.equal(initialized.result.serverInfo.name, "wardn-runtime-smoke");
    const headers = { "MCP-Protocol-Version": initialized.result.protocolVersion };
    const session = initialized.response.headers.get("mcp-session-id");
    if (session) headers["Mcp-Session-Id"] = session;
    await rpc(`${baseUrl}/mcp`, { jsonrpc: "2.0", method: "notifications/initialized" }, headers);
    const listed = await rpc(`${baseUrl}/mcp`, { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }, headers);
    assert.equal(listed.result.tools[0].name, "echo");
    const called = await rpc(`${baseUrl}/mcp`, { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "echo", arguments: { text: "wardn-compatible" } } }, headers);
    assert.deepEqual(called.result.content, [{ type: "text", text: "wardn-compatible" }]);
  } finally {
    try { process.kill(-gateway.pid, "SIGTERM"); } catch { /* It already stopped. */ }
    await Promise.race([once(gateway, "exit"), delay(2000)]);
    if (gateway.exitCode === null) { try { process.kill(-gateway.pid, "SIGKILL"); } catch { /* It already stopped. */ } }
  }
});
