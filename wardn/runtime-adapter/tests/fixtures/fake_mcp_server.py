import json
import sys

initialized = False

for raw_line in sys.stdin:
    line = raw_line.strip()
    if not line:
        continue
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake", "version": "0.1.0"},
                    },
                }
            ),
            flush=True,
        )
    elif method == "notifications/initialized":
        initialized = True
    elif method == "tools/list":
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echo arguments.",
                                "inputSchema": {"type": "object"},
                            }
                        ]
                    },
                }
            ),
            flush=True,
        )
    elif method == "tools/call":
        params = request.get("params") or {}
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "initialized": initialized,
                                        "name": params.get("name"),
                                        "arguments": params.get("arguments") or {},
                                    },
                                    sort_keys=True,
                                ),
                            }
                        ],
                        "isError": False,
                    },
                }
            ),
            flush=True,
        )
    else:
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "method not found"},
                }
            ),
            flush=True,
        )
