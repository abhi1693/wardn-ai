import asyncio
import json
import logging
import os
from collections import deque
from typing import Any

from adapter.config import AdapterSettings
from adapter.redaction import redact_text

PROTOCOL_VERSION = "2025-06-18"
logger = logging.getLogger(__name__)


class AdapterError(Exception):
    pass


class RuntimeNotReadyError(AdapterError):
    pass


class MCPStdioBridge:
    def __init__(self, settings: AdapterSettings) -> None:
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        self.ready = False
        self.start_error = ""
        self._request_lock = asyncio.Lock()
        self._stderr_tail: deque[str] = deque(maxlen=200)
        self._stderr_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self.process and self.process.returncode is None:
            return
        env = dict(os.environ)
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.settings.command,
                *self.settings.args,
                cwd=self.settings.cwd or None,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            self.start_error = f"stdio MCP command was not found: {self.settings.command}"
            raise AdapterError(self.start_error) from exc
        except OSError as exc:
            self.start_error = f"stdio MCP command could not start: {exc}"
            raise AdapterError(self.start_error) from exc

        self._stderr_task = asyncio.create_task(self._read_stderr())
        try:
            await self._initialize()
        except Exception as exc:
            self.start_error = str(exc)
            await self.stop()
            raise

    async def _initialize(self) -> None:
        response = await self.request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "wardn-runtime-adapter", "version": "0.1.0"},
                },
            },
            timeout=self.settings.startup_timeout_seconds,
        )
        if "error" in response:
            raise AdapterError(f"upstream initialize failed: {response['error']}")
        if "result" not in response:
            raise AdapterError("upstream initialize returned no result")
        await self.notify({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self.ready = True
        self.start_error = ""

    async def notify(self, payload: dict[str, Any]) -> None:
        async with self._request_lock:
            await self._send(payload)

    async def request(
        self,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request_id = payload.get("id")
        if request_id is None:
            raise AdapterError("JSON-RPC request must include id")
        async with self._request_lock:
            await self._send(payload)
            return await self._read_response(request_id, timeout=timeout)

    async def _send(self, payload: dict[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise RuntimeNotReadyError("stdio MCP process has no stdin")
        process.stdin.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
        try:
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise RuntimeNotReadyError("stdio MCP process closed stdin") from exc

    async def _read_response(
        self,
        request_id: Any,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        process = self._require_process()
        if process.stdout is None:
            raise RuntimeNotReadyError("stdio MCP process has no stdout")
        deadline = timeout if timeout is not None else self.settings.request_timeout_seconds
        while True:
            if process.returncode is not None:
                suffix = f": {self.stderr_tail()}" if self.stderr_tail() else ""
                raise RuntimeNotReadyError(
                    f"stdio MCP process exited before response {request_id}{suffix}"
                )
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=deadline)
            except TimeoutError as exc:
                raise AdapterError(f"stdio MCP process timed out waiting for {request_id}") from exc
            if not line:
                continue
            try:
                response = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if response.get("id") == request_id:
                return response

    async def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            self._stderr_tail.append(redact_text(line.decode("utf-8", "replace").rstrip()))

    def _require_process(self) -> asyncio.subprocess.Process:
        if self.process is None:
            raise RuntimeNotReadyError("stdio MCP process has not started")
        if self.process.returncode is not None:
            suffix = f": {self.stderr_tail()}" if self.stderr_tail() else ""
            raise RuntimeNotReadyError(f"stdio MCP process exited{suffix}")
        return self.process

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail)[-1000:]

    def status(self) -> dict[str, Any]:
        process = self.process
        return {
            "ready": self.ready and process is not None and process.returncode is None,
            "command": os.path.basename(self.settings.command),
            "pid": process.pid if process else None,
            "returnCode": process.returncode if process else None,
            "lastError": self.start_error,
        }

    async def stop(self) -> None:
        self.ready = False
        process = self.process
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
