#!/usr/bin/env node

import { spawn } from "node:child_process";

const separatorIndex = process.argv.indexOf("--", 2);
const childArgs =
  separatorIndex === -1 ? process.argv.slice(2) : process.argv.slice(separatorIndex + 1);

if (childArgs.length === 0) {
  console.error("structured-content-proxy: missing child command");
  process.exit(2);
}

const child = spawn(childArgs[0], childArgs.slice(1), {
  stdio: ["pipe", "pipe", "pipe"],
});

let stdoutBuffer = "";

function maybeAddStructuredContent(message) {
  if (!message || typeof message !== "object" || Array.isArray(message)) {
    return message;
  }

  const result = message.result;
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    return message;
  }
  if (Object.prototype.hasOwnProperty.call(result, "structuredContent")) {
    return message;
  }

  const content = result.content;
  if (!Array.isArray(content) || content.length === 0) {
    return message;
  }

  const structuredItems = [];
  for (const item of content) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return message;
    }
    if (item.type !== "text" || typeof item.text !== "string") {
      return message;
    }

    const text = item.text.trim();
    if (!text.startsWith("{")) {
      return message;
    }

    let structuredItem;
    try {
      structuredItem = JSON.parse(text);
    } catch {
      return message;
    }

    if (!structuredItem || typeof structuredItem !== "object" || Array.isArray(structuredItem)) {
      return message;
    }

    structuredItems.push(structuredItem);
  }

  const structuredContent =
    structuredItems.length === 1
      ? structuredItems[0]
      : { items: structuredItems, count: structuredItems.length };

  return {
    ...message,
    result: {
      ...result,
      structuredContent,
    },
  };
}

function writeTransformedLine(line) {
  if (!line) {
    return;
  }

  let parsed;
  try {
    parsed = JSON.parse(line);
  } catch {
    process.stdout.write(`${line}\n`);
    return;
  }

  process.stdout.write(`${JSON.stringify(maybeAddStructuredContent(parsed))}\n`);
}

function flushStdoutBuffer(final = false) {
  for (;;) {
    const newlineIndex = stdoutBuffer.indexOf("\n");
    if (newlineIndex === -1) {
      break;
    }

    const line = stdoutBuffer.slice(0, newlineIndex).replace(/\r$/, "");
    stdoutBuffer = stdoutBuffer.slice(newlineIndex + 1);
    writeTransformedLine(line);
  }

  if (final && stdoutBuffer.length > 0) {
    writeTransformedLine(stdoutBuffer.replace(/\r$/, ""));
    stdoutBuffer = "";
  }
}

child.stdout.setEncoding("utf8");
child.stdout.on("data", (chunk) => {
  stdoutBuffer += chunk;
  flushStdoutBuffer();
});
child.stdout.on("end", () => {
  flushStdoutBuffer(true);
});

child.stderr.pipe(process.stderr);
process.stdin.pipe(child.stdin);
child.stdin.on("error", (error) => {
  if (error.code !== "EPIPE") {
    console.error(`structured-content-proxy: child stdin error: ${error.message}`);
  }
});

child.on("error", (error) => {
  console.error(`structured-content-proxy: failed to start child: ${error.message}`);
  process.exitCode = 2;
});

child.on("close", (code, signal) => {
  flushStdoutBuffer(true);
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    if (!child.killed) {
      child.kill(signal);
    }
  });
}
