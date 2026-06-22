import json
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from app.core.config import get_settings
from app.modules.mcp_gateway import client
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime import adapter_client
from app.modules.mcp_runtime.adapter_contract import (
    ADAPTER_READY_PATH,
    WARDN_RUNTIME_ARGS_JSON_ENV,
    WARDN_RUNTIME_COMMAND_ENV,
    WARDN_RUNTIME_CWD_ENV,
    WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS_ENV,
    WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS_ENV,
    adapter_url,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.provider import (
    RUNTIME_HEALTH_NOT_READY,
    RUNTIME_HEALTH_READY,
    RUNTIME_HEALTH_STOPPED,
    RUNTIME_KIND_PACKAGE,
    RUNTIME_PROVIDER_LOCAL,
    RUNTIME_TRANSPORT_STDIO,
    RUNTIME_TRANSPORT_STREAMABLE_HTTP,
    PackageRuntimeSpec,
    RuntimeHealth,
    RuntimeSpec,
    base_runtime_spec,
    package_runtime,
    runtime_kind,
)

TERMINAL_RUNTIME_STATUSES = {"stopped", "failed", "expired"}

RUNTIME_TRANSPORT_ADAPTER = RUNTIME_TRANSPORT_STREAMABLE_HTTP
LOCAL_TRANSPORT_ADAPTER = "adapter"
LOCAL_TRANSPORT_STDIO = "stdio"


@dataclass
class ManagedStdioSession:
    session: client.MCPStdioSession
    next_request_id: int = 2


@dataclass
class ManagedAdapterSession:
    process: subprocess.Popen[bytes]
    endpoint_url: str
    next_request_id: int = 2


class LocalProcessRuntimeProvider:
    name = RUNTIME_PROVIDER_LOCAL

    def __init__(self) -> None:
        self._stdio_sessions: dict[str, ManagedStdioSession] = {}
        self._stdio_lock = Lock()
        self._adapter_sessions: dict[str, ManagedAdapterSession] = {}
        self._adapter_lock = Lock()

    def supports(self, installation: MCPServerInstallation) -> bool:
        return runtime_kind(installation) == RUNTIME_KIND_PACKAGE

    def runtime_spec(self, installation: MCPServerInstallation) -> RuntimeSpec:
        runtime = package_runtime(installation)
        transport = (
            RUNTIME_TRANSPORT_ADAPTER
            if self._use_adapter()
            else RUNTIME_TRANSPORT_STDIO
        )
        return base_runtime_spec(
            installation,
            provider_name=self.name,
            transport=transport,
            command=runtime.command,
            args=runtime.args,
            cwd=runtime.cwd,
        )

    def list_tools(self, installation: MCPServerInstallation) -> list[dict[str, Any]]:
        runtime = package_runtime(installation)
        if self._use_adapter():
            return self._with_adapter_session(
                installation,
                runtime=runtime,
                action=self._list_adapter_tools,
            )
        return client.list_stdio_tools(
            runtime.command,
            runtime.args,
            cwd=runtime.cwd,
            environment=runtime.environment,
        )

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        runtime_session: MCPRuntimeSession | None = None,
    ) -> dict[str, Any]:
        runtime = package_runtime(installation)
        if self._use_adapter():
            return self._with_adapter_session(
                installation,
                runtime=runtime,
                runtime_session=runtime_session,
                action=lambda managed: self._call_adapter_tool(
                    managed,
                    tool_name=tool_name,
                    arguments=arguments,
                ),
            )
        return self._with_stdio_session(
            installation,
            runtime=runtime,
            action=lambda managed: self._call_stdio_tool(
                managed,
                tool_name=tool_name,
                arguments=arguments,
            ),
        )

    def stop_runtime(self, runtime_session: MCPRuntimeSession) -> None:
        self._drop_stdio_session(runtime_session.config_fingerprint)
        self._drop_adapter_session(runtime_session.config_fingerprint)

    def health(self, runtime_session: MCPRuntimeSession) -> RuntimeHealth:
        if runtime_session.status in TERMINAL_RUNTIME_STATUSES:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_STOPPED,
                healthy=False,
                ready=False,
                message=f"Runtime session is {runtime_session.status}.",
            )

        adapter_health = self._adapter_session_health(runtime_session)
        if adapter_health is not None:
            return adapter_health

        stdio_health = self._stdio_session_health(runtime_session)
        if stdio_health is not None:
            return stdio_health

        return RuntimeHealth(
            status=RUNTIME_HEALTH_NOT_READY,
            healthy=False,
            ready=False,
            message="Local runtime process is not present in this backend process.",
        )

    def stop_all(self) -> None:
        with self._stdio_lock:
            stdio_keys = list(self._stdio_sessions)
        with self._adapter_lock:
            adapter_keys = list(self._adapter_sessions)
        for key in stdio_keys:
            self._drop_stdio_session(key)
        for key in adapter_keys:
            self._drop_adapter_session(key)

    def _use_adapter(self) -> bool:
        return get_settings().mcp_runtime_local_transport.lower() == LOCAL_TRANSPORT_ADAPTER

    def _session_key(
        self,
        installation: MCPServerInstallation,
        *,
        runtime: PackageRuntimeSpec,
        transport: str,
    ) -> str:
        return base_runtime_spec(
            installation,
            provider_name=self.name,
            transport=transport,
            command=runtime.command,
            args=runtime.args,
            cwd=runtime.cwd,
        ).fingerprint()

    def _stdio_session_key(
        self,
        installation: MCPServerInstallation,
        *,
        runtime: PackageRuntimeSpec,
    ) -> str:
        return self._session_key(
            installation,
            runtime=runtime,
            transport=RUNTIME_TRANSPORT_STDIO,
        )

    def _adapter_session_key(
        self,
        installation: MCPServerInstallation,
        *,
        runtime: PackageRuntimeSpec,
    ) -> str:
        return self._session_key(
            installation,
            runtime=runtime,
            transport=RUNTIME_TRANSPORT_ADAPTER,
        )

    def _with_stdio_session(
        self,
        installation: MCPServerInstallation,
        *,
        runtime: PackageRuntimeSpec,
        action: Callable[[ManagedStdioSession], Any],
    ) -> Any:
        key = self._stdio_session_key(installation, runtime=runtime)
        with self._stdio_lock:
            managed = self._stdio_sessions.get(key)
            if managed is None or managed.session.process.poll() is not None:
                managed = ManagedStdioSession(
                    client.open_stdio_session(
                        runtime.command,
                        runtime.args,
                        cwd=runtime.cwd,
                        environment=runtime.environment,
                    )
                )
                self._stdio_sessions[key] = managed
            try:
                return action(managed)
            except Exception:
                self._drop_stdio_session(key)
                raise

    def _drop_stdio_session(self, key: str) -> None:
        managed = self._stdio_sessions.pop(key, None)
        if managed is not None:
            client.close_stdio_session(managed.session)

    def _with_adapter_session(
        self,
        installation: MCPServerInstallation,
        *,
        runtime: PackageRuntimeSpec,
        action: Callable[[ManagedAdapterSession], Any],
        runtime_session: MCPRuntimeSession | None = None,
    ) -> Any:
        key = self._adapter_session_key(installation, runtime=runtime)
        with self._adapter_lock:
            managed = self._adapter_sessions.get(key)
            if managed is None or managed.process.poll() is not None:
                managed = self._start_adapter_session(runtime)
                self._adapter_sessions[key] = managed
            if runtime_session is not None:
                runtime_session.endpoint_url = managed.endpoint_url
            try:
                return action(managed)
            except Exception:
                self._drop_adapter_session(key)
                raise

    def _start_adapter_session(self, runtime: PackageRuntimeSpec) -> ManagedAdapterSession:
        port = self._free_local_port()
        endpoint_url = f"http://127.0.0.1:{port}"
        adapter_root = self._adapter_root()
        env = {
            **runtime.environment,
            WARDN_RUNTIME_COMMAND_ENV: runtime.command,
            WARDN_RUNTIME_ARGS_JSON_ENV: json.dumps(runtime.args),
            WARDN_RUNTIME_CWD_ENV: runtime.cwd,
            WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS_ENV: str(
                get_settings().mcp_runtime_adapter_startup_timeout_seconds
            ),
            WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS_ENV: str(
                get_settings().mcp_runtime_adapter_request_timeout_seconds
            ),
        }
        process_env = {
            **self._process_environment(),
            **env,
            "PYTHONPATH": str(adapter_root),
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "adapter.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=str(adapter_root),
            env=process_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        managed = ManagedAdapterSession(process=process, endpoint_url=endpoint_url)
        try:
            self._wait_for_adapter_ready(managed)
        except Exception:
            self._terminate_adapter_process(process)
            raise
        return managed

    def _drop_adapter_session(self, key: str) -> None:
        managed = self._adapter_sessions.pop(key, None)
        if managed is not None:
            self._terminate_adapter_process(managed.process)

    def _terminate_adapter_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _adapter_session_health(
        self,
        runtime_session: MCPRuntimeSession,
    ) -> RuntimeHealth | None:
        with self._adapter_lock:
            managed = self._adapter_sessions.get(runtime_session.config_fingerprint)
        if managed is None:
            return None

        return_code = managed.process.poll()
        details: dict[str, Any] = {
            "transport": RUNTIME_TRANSPORT_ADAPTER,
            "processId": managed.process.pid,
            "returnCode": return_code,
        }
        if return_code is not None:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_NOT_READY,
                healthy=False,
                ready=False,
                message="Runtime adapter process has exited.",
                details=details,
            )

        try:
            status_payload = adapter_client.get_adapter_status(managed.endpoint_url)
        except adapter_client.MCPRuntimeAdapterError as exc:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_NOT_READY,
                healthy=False,
                ready=False,
                message=str(exc),
                details=details,
            )

        ready = bool(status_payload.get("ready"))
        details.update({"adapter": status_payload})
        return RuntimeHealth(
            status=RUNTIME_HEALTH_READY if ready else RUNTIME_HEALTH_NOT_READY,
            healthy=ready,
            ready=ready,
            message="Runtime adapter is ready." if ready else "Runtime adapter is not ready.",
            details=details,
        )

    def _stdio_session_health(
        self,
        runtime_session: MCPRuntimeSession,
    ) -> RuntimeHealth | None:
        with self._stdio_lock:
            managed = self._stdio_sessions.get(runtime_session.config_fingerprint)
        if managed is None:
            return None

        return_code = managed.session.process.poll()
        details = {
            "transport": RUNTIME_TRANSPORT_STDIO,
            "processId": managed.session.process.pid,
            "returnCode": return_code,
        }
        if return_code is not None:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_NOT_READY,
                healthy=False,
                ready=False,
                message="Local stdio runtime process has exited.",
                details=details,
            )
        return RuntimeHealth(
            status=RUNTIME_HEALTH_READY,
            healthy=True,
            ready=True,
            message="Local stdio runtime process is running.",
            details=details,
        )

    def _wait_for_adapter_ready(self, managed: ManagedAdapterSession) -> None:
        deadline = time.monotonic() + get_settings().mcp_runtime_adapter_startup_timeout_seconds
        ready_url = adapter_url(managed.endpoint_url, ADAPTER_READY_PATH)
        last_error = ""
        while time.monotonic() < deadline:
            if managed.process.poll() is not None:
                raise RuntimeError("runtime adapter process exited before readiness")
            try:
                with urlopen(ready_url, timeout=1) as response:
                    if response.status == 200:
                        return
            except HTTPError as exc:
                last_error = str(exc)
            except (TimeoutError, URLError, OSError) as exc:
                last_error = str(exc)
            time.sleep(0.1)
        raise RuntimeError(f"runtime adapter did not become ready: {last_error}")

    def _list_adapter_tools(self, managed: ManagedAdapterSession) -> list[dict[str, Any]]:
        tools, next_request_id = adapter_client.list_tools(
            managed.endpoint_url,
            request_id_start=managed.next_request_id,
        )
        managed.next_request_id = next_request_id
        return tools

    def _call_adapter_tool(
        self,
        managed: ManagedAdapterSession,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = managed.next_request_id
        managed.next_request_id += 1
        return adapter_client.call_tool(
            managed.endpoint_url,
            request_id=request_id,
            tool_name=tool_name,
            arguments=arguments,
        )

    def _free_local_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _adapter_root(self) -> Path:
        return Path(__file__).resolve().parents[5] / "runtime-adapter"

    def _process_environment(self) -> dict[str, str]:
        import os

        return dict(os.environ)

    def _list_stdio_tools(self, managed: ManagedStdioSession) -> list[dict[str, Any]]:
        tools, next_request_id = client.list_stdio_session_tools(
            managed.session,
            request_id_start=managed.next_request_id,
        )
        managed.next_request_id = next_request_id
        return tools

    def _call_stdio_tool(
        self,
        managed: ManagedStdioSession,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = managed.next_request_id
        managed.next_request_id += 1
        return client.call_stdio_session_tool(
            managed.session,
            request_id=request_id,
            tool_name=tool_name,
            arguments=arguments,
        )
