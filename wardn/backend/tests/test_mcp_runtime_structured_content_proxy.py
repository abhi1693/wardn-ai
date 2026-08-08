import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is required for the runtime proxy test")
def test_structured_content_proxy_adds_missing_structured_content() -> None:
    proxy_path = (
        Path(__file__).resolve().parents[2]
        / "mcp-runtime"
        / "structured-content-proxy.mjs"
    )
    child_script = r"""
process.stdin.setEncoding("utf8");
let buffer = "";
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  for (;;) {
    const newlineIndex = buffer.indexOf("\n");
    if (newlineIndex === -1) {
      break;
    }
    const line = buffer.slice(0, newlineIndex);
    buffer = buffer.slice(newlineIndex + 1);
    const request = JSON.parse(line);
    process.stdout.write(JSON.stringify({
      jsonrpc: "2.0",
      id: request.id,
      result: {
        content: [
          {
            type: "text",
            text: "{\"tools\":[{\"name\":\"access_list_doors\"}],\"count\":1}"
          }
        ],
        isError: false
      }
    }) + "\n");
  }
});
"""

    completed = subprocess.run(
        [NODE, str(proxy_path), "--", NODE, "-e", child_script],
        input='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}\n',
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )

    response = json.loads(completed.stdout)
    assert response["result"]["structuredContent"] == {
        "tools": [{"name": "access_list_doors"}],
        "count": 1,
    }


@pytest.mark.skipif(NODE is None, reason="node is required for the runtime proxy test")
def test_structured_content_proxy_adds_array_structured_content() -> None:
    proxy_path = (
        Path(__file__).resolve().parents[2]
        / "mcp-runtime"
        / "structured-content-proxy.mjs"
    )
    child_script = r"""
process.stdin.setEncoding("utf8");
let buffer = "";
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  for (;;) {
    const newlineIndex = buffer.indexOf("\n");
    if (newlineIndex === -1) {
      break;
    }
    const line = buffer.slice(0, newlineIndex);
    buffer = buffer.slice(newlineIndex + 1);
    const request = JSON.parse(line);
    const regions = [
      {
        slug: "nyc1",
        name: "New York 1",
        sizes: ["s-1vcpu-1gb"],
        available: true
      },
      {
        slug: "sfo1",
        name: "San Francisco 1"
      }
    ];
    process.stdout.write(JSON.stringify({
      jsonrpc: "2.0",
      id: request.id,
      result: {
        content: [
          {
            type: "text",
            text: JSON.stringify(regions)
          }
        ],
        isError: false
      }
    }) + "\n");
  }
});
"""

    completed = subprocess.run(
        [NODE, str(proxy_path), "--", NODE, "-e", child_script],
        input='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}\n',
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )

    response = json.loads(completed.stdout)
    assert response["result"]["structuredContent"] == [
        {
            "slug": "nyc1",
            "name": "New York 1",
            "sizes": ["s-1vcpu-1gb"],
            "available": True,
        },
        {"slug": "sfo1", "name": "San Francisco 1"},
    ]


@pytest.mark.skipif(NODE is None, reason="node is required for the runtime proxy test")
def test_structured_content_proxy_wraps_multiple_json_text_items() -> None:
    proxy_path = (
        Path(__file__).resolve().parents[2]
        / "mcp-runtime"
        / "structured-content-proxy.mjs"
    )
    child_script = r"""
process.stdin.setEncoding("utf8");
let buffer = "";
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  for (;;) {
    const newlineIndex = buffer.indexOf("\n");
    if (newlineIndex === -1) {
      break;
    }
    const line = buffer.slice(0, newlineIndex);
    buffer = buffer.slice(newlineIndex + 1);
    const request = JSON.parse(line);
    process.stdout.write(JSON.stringify({
      jsonrpc: "2.0",
      id: request.id,
      result: {
        content: [
          {
            type: "text",
            text: "{\"group\":\"apps\",\"versions\":[\"v1\"],\"preferred\":\"v1\"}"
          },
          {
            type: "text",
            text: "{\"group\":\"batch\",\"versions\":[\"v1\"],\"preferred\":\"v1\"}"
          }
        ],
        isError: false
      }
    }) + "\n");
  }
});
"""

    completed = subprocess.run(
        [NODE, str(proxy_path), "--", NODE, "-e", child_script],
        input='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}\n',
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )

    response = json.loads(completed.stdout)
    assert response["result"]["structuredContent"] == {
        "items": [
            {"group": "apps", "versions": ["v1"], "preferred": "v1"},
            {"group": "batch", "versions": ["v1"], "preferred": "v1"},
        ],
        "count": 2,
    }
