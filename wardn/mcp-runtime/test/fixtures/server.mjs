import { createInterface } from "node:readline";

// Local deterministic MCP server. No network access or application credentials.
createInterface({ input: process.stdin }).on("line", (line) => {
  const message = JSON.parse(line);
  if (message.id === undefined) return;
  let result;
  switch (message.method) {
    case "initialize":
      result = {
        protocolVersion: message.params.protocolVersion,
        capabilities: { tools: {} },
        serverInfo: { name: "wardn-runtime-smoke", version: "1.0.0" },
      };
      break;
    case "tools/list":
      result = { tools: [{
        name: "echo", description: "Echo test text",
        inputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
      }] };
      break;
    case "tools/call":
      result = { content: [{ type: "text", text: message.params.arguments.text }] };
      break;
    case "ping":
      result = {};
      break;
    default:
      process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: message.id, error: { code: -32601, message: "Unknown method" } }) + "\n");
      return;
  }
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: message.id, result }) + "\n");
});
